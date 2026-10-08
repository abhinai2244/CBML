#!/usr/bin/env python3
"""
Generate Google Service Accounts

This script creates Google Cloud projects, service accounts, and downloads
credentials for use with Google Drive API operations.
"""

from argparse import ArgumentParser, RawDescriptionHelpFormatter
from base64 import b64decode
from errno import EEXIST
from glob import glob
from json import loads
from os import mkdir, path as ospath
from pickle import dump, load
from random import choice
from sys import exit
from time import sleep

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/iam",
]

project_create_ops = []
current_key_dump = []
sleep_time = 30
CHARS = "-abcdefghijklmnopqrstuvwxyz1234567890"


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_step(step: int, total: int, message: str) -> None:
    """Print a step indicator."""
    print(f"\n[{step}/{total}] {message}")


def _create_accounts(service, project, count):
    """Create service accounts in a project."""
    batch = service.new_batch_http_request(callback=_def_batch_resp)
    for _ in range(count):
        aid = _generate_id("mfc-")
        batch.add(
            service.projects()
            .serviceAccounts()
            .create(
                name=f"projects/{project}",
                body={
                    "accountId": aid,
                    "serviceAccount": {"displayName": aid},
                },
            )
        )
    try:
        batch.execute()
    except HttpError as e:
        print("Error creating accounts:", e)


def _create_remaining_accounts(iam, project):
    """Create remaining accounts to reach 100."""
    print(f"Creating accounts in {project}")
    sa_count = len(_list_sas(iam, project))
    while sa_count != 100:
        _create_accounts(iam, project, 100 - sa_count)
        sa_count = len(_list_sas(iam, project))


def _generate_id(prefix="saf-"):
    """Generate a random ID."""
    return prefix + "".join(choice(CHARS) for _ in range(25)) + choice(CHARS[1:])


def _get_projects(service):
    """Get list of projects."""
    try:
        return [i["projectId"] for i in service.projects().list().execute()["projects"]]
    except HttpError as e:
        print("Error fetching projects:", e)
        return []


def _def_batch_resp(id, resp, exception):
    """Handle batch responses."""
    global sleep_time
    if exception is not None:
        if str(exception).startswith("<HttpError 429"):
            sleep(sleep_time / 100)
        else:
            print("Batch error:", exception)


def _pc_resp(id, resp, exception):
    """Handle project creation responses."""
    global project_create_ops
    if exception is not None:
        print("Project creation error:", exception)
    else:
        for i in resp.values():
            project_create_ops.append(i)


def _create_projects(cloud, count):
    """Create new Google Cloud projects."""
    global project_create_ops
    batch = cloud.new_batch_http_request(callback=_pc_resp)
    new_projs = []
    for _ in range(count):
        new_proj = _generate_id()
        new_projs.append(new_proj)
        batch.add(cloud.projects().create(body={"project_id": new_proj}))
    try:
        batch.execute()
    except HttpError as e:
        print("Error creating projects:", e)
        return []

    for op in project_create_ops:
        while True:
            try:
                resp = cloud.operations().get(name=op).execute()
                if resp.get("done"):
                    break
            except HttpError as e:
                print("Error fetching operation status:", e)
                break
            sleep(3)
    return new_projs


def _enable_services(service, projects, ste):
    """Enable services on projects."""
    batch = service.new_batch_http_request(callback=_def_batch_resp)
    for project in projects:
        for s in ste:
            batch.add(
                service.services().enable(name=f"projects/{project}/services/{s}")
            )
    try:
        batch.execute()
    except HttpError as e:
        print("Error enabling services:", e)


def _list_sas(iam, project):
    """List service accounts in a project."""
    try:
        resp = (
            iam.projects()
            .serviceAccounts()
            .list(name=f"projects/{project}", pageSize=100)
            .execute()
        )
        return resp.get("accounts", [])
    except HttpError as e:
        print("Error listing service accounts:", e)
        return []


def _batch_keys_resp(id, resp, exception):
    """Handle key creation batch responses."""
    global current_key_dump
    if exception is not None:
        current_key_dump = None
        sleep(sleep_time / 100)
    elif current_key_dump is None:
        sleep(sleep_time / 100)
    else:
        try:
            key_name = resp["name"][resp["name"].rfind("/") :]
            key_data = b64decode(resp["privateKeyData"]).decode("utf-8")
            current_key_dump.append((key_name, key_data))
        except Exception as e:
            print("Error processing key response:", e)


def _create_sa_keys(iam, projects, path_dir):
    """Download service account keys."""
    global current_key_dump
    for project in projects:
        current_key_dump = []
        print(f"Downloading keys from {project}")
        while current_key_dump is None or len(current_key_dump) != 100:
            batch = iam.new_batch_http_request(callback=_batch_keys_resp)
            total_sas = _list_sas(iam, project)
            for sa in total_sas:
                batch.add(
                    iam.projects()
                    .serviceAccounts()
                    .keys()
                    .create(
                        name=f"projects/{project}/serviceAccounts/{sa['uniqueId']}",
                        body={
                            "privateKeyType": "TYPE_GOOGLE_CREDENTIALS_FILE",
                            "keyAlgorithm": "KEY_ALG_RSA_2048",
                        },
                    )
                )
            try:
                batch.execute()
            except HttpError as e:
                print("Error creating SA keys:", e)
                current_key_dump = None

            if current_key_dump is None:
                print(f"Redownloading keys from {project}")
                current_key_dump = []
            else:
                for index, key in enumerate(current_key_dump):
                    try:
                        with open(f"{path_dir}/{index}.json", "w+") as f:
                            f.write(key[1])
                    except IOError as e:
                        print(f"Error writing key file {index}.json:", e)


def _delete_sas(iam, project):
    """Delete all service accounts in a project."""
    sas = _list_sas(iam, project)
    batch = iam.new_batch_http_request(callback=_def_batch_resp)
    for account in sas:
        batch.add(iam.projects().serviceAccounts().delete(name=account["name"]))
    try:
        batch.execute()
    except HttpError as e:
        print("Error deleting service accounts:", e)


def serviceaccountfactory(
    credentials="../../config/credentials.json",
    token="../../config/tokens/token_sa.pickle",
    path=None,
    list_projects=False,
    list_sas=None,
    create_projects=None,
    max_projects=12,
    enable_services=None,
    services=["iam", "drive"],
    create_sas=None,
    delete_sas=None,
    download_keys=None,
):
    """Main function to manage service accounts."""
    selected_projects = []
    try:
        proj_id = loads(open(credentials, "r").read())["installed"]["project_id"]
    except Exception as e:
        exit("Error reading credentials file: " + str(e))

    creds = None
    if path and not path:
        path = "accounts"
    if path and not path.endswith("/"):
        path = path.rstrip("/")

    if path and not path == "accounts":
        try:
            mkdir(path)
        except OSError as e:
            if e.errno != EEXIST:
                print("Error creating output directory:", e)
                exit(1)

    if ospath.exists(token):
        try:
            with open(token, "rb") as t:
                creds = load(t)
        except Exception as e:
            print("Error loading token file:", e)
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials, SCOPES)
                creds = flow.run_local_server(port=0, open_browser=False)
            with open(token, "wb") as t:
                dump(creds, t)
        except Exception as e:
            exit("Error obtaining credentials: " + str(e))

    try:
        cloud = build("cloudresourcemanager", "v1", credentials=creds)
        iam = build("iam", "v1", credentials=creds)
        serviceusage = build("serviceusage", "v1", credentials=creds)
    except Exception as e:
        exit("Error building service clients: " + str(e))

    projs = None
    while projs is None:
        try:
            projs = _get_projects(cloud)
        except HttpError:
            try:
                serviceusage.services().enable(
                    name=f"projects/{proj_id}/services/cloudresourcemanager.googleapis.com"
                ).execute()
            except HttpError as ee:
                print("Error enabling cloudresourcemanager:", ee)
                input("Press Enter to retry.")
    if list_projects:
        return _get_projects(cloud)
    if list_sas:
        return _list_sas(iam, list_sas)
    if create_projects:
        print(f"Creating projects: {create_projects}")
        if create_projects > 0:
            current_count = len(_get_projects(cloud))
            if current_count + create_projects <= max_projects:
                print("Creating %d projects" % create_projects)
                nprjs = _create_projects(cloud, create_projects)
                selected_projects = nprjs
            else:
                exit(
                    "Cannot create %d new project(s).\n"
                    "Please reduce the value or delete existing projects.\n"
                    "Max projects allowed: %d, already in use: %d"
                    % (create_projects, max_projects, current_count)
                )
        else:
            print("Overwriting all service accounts in existing projects.")
            input("Press Enter to continue...")

    if enable_services:
        target = [enable_services]
        if enable_services == "~":
            target = selected_projects
        elif enable_services == "*":
            target = _get_projects(cloud)
        service_list = [f"{s}.googleapis.com" for s in services]
        print("Enabling services")
        _enable_services(serviceusage, target, service_list)
    if create_sas:
        target = [create_sas]
        if create_sas == "~":
            target = selected_projects
        elif create_sas == "*":
            target = _get_projects(cloud)
        for proj in target:
            _create_remaining_accounts(iam, proj)
    if download_keys:
        target = [download_keys]
        if download_keys == "~":
            target = selected_projects
        elif download_keys == "*":
            target = _get_projects(cloud)
        _create_sa_keys(iam, target, path)
    if delete_sas:
        target = [delete_sas]
        if delete_sas == "~":
            target = selected_projects
        elif delete_sas == "*":
            target = _get_projects(cloud)
        for proj in target:
            print(f"Deleting service accounts in {proj}")
            _delete_sas(iam, proj)


def main():
    epilog = """
Examples:
  # Quick setup - create 5 projects with service accounts
  python script.py --quick-setup 5

  # List all projects
  python script.py --list-projects

  # List service accounts in a specific project
  python script.py --list-sas <project-id>

  # Enable services on all projects
  python script.py --enable-services "*"

  # Download keys from a specific project
  python script.py --download-keys <project-id>

  # Full workflow with custom path
  python script.py --quick-setup 3 --path ./my_accounts --max-projects 12

Workflow:
  1. Run with --quick-setup N to create N projects with service accounts
  2. Use --download-keys to get credential files for each project
  3. Use add_to_team_drive script to add accounts to your Team Drive
"""
    parser = ArgumentParser(
        description="Google Service Account Generator",
        epilog=epilog,
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--path",
        "-p",
        default="accounts",
        help="Directory to output credential files (default: accounts)",
    )
    parser.add_argument(
        "--token", default="../../config/tokens/token_sa.pickle", help="Token file path"
    )
    parser.add_argument(
        "--credentials",
        default="../../config/credentials.json",
        help="Credentials file path",
    )
    parser.add_argument(
        "--list-projects",
        default=False,
        action="store_true",
        help="List all projects viewable by the user",
    )
    parser.add_argument(
        "--list-sas", default=False, help="List service accounts in a specific project"
    )
    parser.add_argument(
        "--create-projects", type=int, default=None, help="Create N new projects"
    )
    parser.add_argument(
        "--max-projects",
        type=int,
        default=12,
        help="Maximum projects allowed (default: 12)",
    )
    parser.add_argument(
        "--enable-services",
        default=None,
        help="Enable services on projects ('*' for all, '~' for newly created)",
    )
    parser.add_argument(
        "--services",
        nargs="+",
        default=["iam", "drive"],
        help="Services to enable (default: iam drive)",
    )
    parser.add_argument(
        "--create-sas",
        default=None,
        help="Create service accounts in a project ('*' for all, '~' for newly created)",
    )
    parser.add_argument(
        "--delete-sas",
        default=None,
        help="Delete service accounts in a project ('*' for all, '~' for newly created)",
    )
    parser.add_argument(
        "--download-keys",
        default=None,
        help="Download keys for service accounts ('*' for all, '~' for newly created)",
    )
    parser.add_argument(
        "--quick-setup",
        default=None,
        type=int,
        help="Create N projects with full setup (projects + SAs + keys)",
    )
    parser.add_argument(
        "--new-only",
        default=False,
        action="store_true",
        help="Only use newly created projects (used with --quick-setup)",
    )
    args = parser.parse_args()

    print_header("Google Service Account Generator")

    if not ospath.exists(args.credentials):
        options = glob("*.json")
        print(f"\n[ERROR] No credentials found at {args.credentials}")
        print("\nTo get credentials:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project")
        print("3. Enable these APIs:")
        print("   - Cloud Resource Manager API")
        print("   - IAM API")
        print("   - Service Usage API")
        print("   - Google Drive API")
        print("4. Create OAuth 2.0 credentials (Desktop app)")
        print("5. Download as 'credentials.json'")
        print("\nOr use the gen_token_pickle script first.")
        if not options:
            exit("No credential files found in current directory.")
        else:
            print("\nFound these JSON files:")
            for idx, opt in enumerate(options):
                print(f"  {idx + 1}) {opt}")
            while True:
                inp = input("\nSelect a credentials file (number or name): ").strip()
                try:
                    choice_idx = int(inp) - 1
                    if 0 <= choice_idx < len(options):
                        args.credentials = options[choice_idx]
                        break
                except ValueError:
                    if inp in options:
                        args.credentials = inp
                        break
            print(f"Using: {args.credentials}")

    if args.quick_setup:
        print(f"\n[INFO] Quick setup mode: Creating {args.quick_setup} projects")
        opt = "~" if args.new_only else "*"
        args.services = ["iam", "drive"]
        args.create_projects = args.quick_setup
        args.enable_services = opt
        args.create_sas = opt
        args.download_keys = opt

    resp = serviceaccountfactory(
        path=args.path,
        token=args.token,
        credentials=args.credentials,
        list_projects=args.list_projects,
        list_sas=args.list_sas,
        create_projects=args.create_projects,
        max_projects=args.max_projects,
        create_sas=args.create_sas,
        delete_sas=args.delete_sas,
        enable_services=args.enable_services,
        services=args.services,
        download_keys=args.download_keys,
    )

    if resp is not None:
        if args.list_projects:
            if resp:
                print("\nProjects (%d):" % len(resp))
                for proj in resp:
                    print(f"  - {proj}")
            else:
                print("No projects found.")
        elif args.list_sas:
            if resp:
                print(f"\nService accounts in {args.list_sas} (%d):" % len(resp))
                for sa in resp:
                    print(f"  - {sa['email']}")
            else:
                print("No service accounts found.")

    if args.quick_setup:
        print("\n" + "=" * 60)
        print("  SETUP COMPLETE!")
        print("=" * 60)
        print(f"\nCredentials saved to: {args.path}/")
        print("\nNext steps:")
        print("1. Run add_to_team_drive to add accounts to your Team Drive")
        print("2. Copy credentials to your bot's accounts folder")


if __name__ == "__main__":
    main()
