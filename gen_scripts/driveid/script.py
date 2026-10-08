#!/usr/bin/env python3
"""
Configure Drive List

This script helps configure the list of Google Drive/Team Drives
that the bot will search through.
"""

import os
import sys
from re import match

DRIVES_FILE = "list_drives.txt"


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50)


def print_step(step: int, total: int, message: str) -> None:
    """Print a step indicator."""
    print(f"\n[{step}/{total}] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"  ℹ {message}")


def main():
    print_header("Google Drive Configuration")

    print("\nThis script configures the list of drives the bot can search.")
    print("You can add multiple drives or folders.\n")

    # Show format explanation
    print_info("Format: NAME ID INDEX_URL")
    print_info("  - NAME: Anything you like (e.g., My_TeamDrive)")
    print_info("  - ID: Drive ID (use 'root' for main drive)")
    print_info("  - INDEX_URL: Optional, for indexing (e.g., https://example.com)")
    print()

    # Step 1: Check existing drives
    print_step(1, 3, "Checking existing configuration...")

    existing_content = ""
    if os.path.exists(DRIVES_FILE):
        try:
            with open(DRIVES_FILE, "r") as f:
                existing_content = f.read()
        except Exception as e:
            print(f"[WARN] Could not read existing file: {e}")

    if existing_content and not match(r"^\s*$", existing_content):
        print(f"\n[INFO] Existing drives found in {DRIVES_FILE}:")
        print("-" * 40)
        print(existing_content)
        print("-" * 40)

        while True:
            choice = input("\nKeep existing drives? (y/n): ").strip().lower()
            if choice == "y":
                msg = existing_content
                break
            elif choice == "n":
                msg = ""
                break
            print("[ERROR] Please enter 'y' or 'n'")
    else:
        msg = ""
        print("[INFO] No existing configuration found.")

    # Step 2: Get number of drives
    print_step(2, 3, "Enter drive details...")

    while True:
        try:
            num = int(input("\nHow many drives/folders you want to add? "))
            if num > 0:
                break
            print("[ERROR] Please enter a positive number.")
        except ValueError:
            print("[ERROR] Invalid number. Please enter an integer.")

    # Step 3: Enter each drive
    print_step(3, 3, "Adding drives...")

    for count in range(1, num + 1):
        print(f"\n--- Drive {count} ---")

        while True:
            name = input("  Name (anything): ").strip()
            if name:
                break
            print("[ERROR] Name cannot be empty.")

        while True:
            drive_id = input("  Drive ID (use 'root' for main drive): ").strip()
            if drive_id:
                break
            print("[ERROR] Drive ID cannot be empty.")

        index_url = input("  Index URL (optional, press Enter to skip): ").strip()

        # Clean up inputs
        name = name.replace(" ", "_")
        if index_url:
            index_url = index_url.rstrip("/")
        else:
            index_url = ""

        msg += f"{name} {drive_id} {index_url}\n"
        print(f"  [OK] Added: {name}")

    # Save to file
    try:
        with open(DRIVES_FILE, "w") as f:
            f.write(msg)
        print(f"\n[OK] Configuration saved to {DRIVES_FILE}")
    except Exception as e:
        print(f"\n[ERROR] Failed to save: {e}")
        sys.exit(1)

    # Show summary
    print("\n" + "=" * 50)
    print("  CONFIGURATION COMPLETE")
    print("=" * 50)
    print(f"\nTotal drives configured: {num}")
    print(f"File: {DRIVES_FILE}")
    print("\nYou can now use the bot with these drives.")


if __name__ == "__main__":
    main()
