from niquests import AsyncSession
from html import escape
from urllib.parse import quote
from pyrogram.enums import ButtonStyle

from .. import LOGGER
from ..core.config_manager import Config
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import get_readable_file_size
from ..helper.ext_utils.telegraph_helper import telegraph
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import edit_message, send_message

PLUGINS = []
SITES = None
TELEGRAPH_LIMIT = 300


async def initiate_search_tools():
    if Config.DISABLE_TORRENTS or Config.DISABLE_SEARCH:
        LOGGER.warning("Torrents are disabled. Skipping search plugin initialization.")
        return
    qb_plugins = await TorrentManager.qbittorrent.search.plugins()
    if qb_plugins:
        names = [plugin.name for plugin in qb_plugins]
        await TorrentManager.qbittorrent.search.uninstall_plugin(names)
        PLUGINS.clear()
    if Config.SEARCH_PLUGINS:
        await TorrentManager.qbittorrent.search.install_plugin(Config.SEARCH_PLUGINS)

    if Config.SEARCH_API_LINK:
        global SITES
        try:
            async with AsyncSession() as client:
                response = await client.get(f"{Config.SEARCH_API_LINK}/api/v1/sites")
                data = response.json()
            SITES = {
                str(site): str(site).capitalize() for site in data["supported_sites"]
            }
            SITES["all"] = "All Sites"
        except Exception as e:
            LOGGER.error(
                f"{e} Can't fetch sites from SEARCH_API_LINK. Ensure latest API version is used."
            )
            SITES = None


async def search(key, site, message, method):
    if method.startswith("api"):
        if method == "apisearch":
            LOGGER.info(f"API Searching: {key} from {site}")
            if site == "all":
                api = f"{Config.SEARCH_API_LINK}/api/v1/all/search?query={key}&limit={Config.SEARCH_LIMIT}"
            else:
                api = f"{Config.SEARCH_API_LINK}/api/v1/search?site={site}&query={key}&limit={Config.SEARCH_LIMIT}"
        elif method == "apitrend":
            LOGGER.info(f"API Trending from {site}")
            if site == "all":
                api = f"{Config.SEARCH_API_LINK}/api/v1/all/trending?limit={Config.SEARCH_LIMIT}"
            else:
                api = f"{Config.SEARCH_API_LINK}/api/v1/trending?site={site}&limit={Config.SEARCH_LIMIT}"
        elif method == "apirecent":
            LOGGER.info(f"API Recent from {site}")
            if site == "all":
                api = f"{Config.SEARCH_API_LINK}/api/v1/all/recent?limit={Config.SEARCH_LIMIT}"
            else:
                api = f"{Config.SEARCH_API_LINK}/api/v1/recent?site={site}&limit={Config.SEARCH_LIMIT}"
        try:
            async with AsyncSession() as client:
                response = await client.get(api)
                search_results = response.json()
            if "error" in search_results or search_results["total"] == 0:
                await edit_message(
                    message,
                    f"<b>No results found for:</b> <code>{key}</code>\n<blockquote>Site: {SITES.get(site)}</blockquote>",
                )
                return
            msg = f"<b>Found {min(search_results['total'], TELEGRAPH_LIMIT)} result(s)</b>"
            if method == "apitrend":
                msg += f"\n<blockquote><b>Type:</b> Trending | <b>Site:</b> {SITES.get(site)}</blockquote>"
            elif method == "apirecent":
                msg += f"\n<blockquote><b>Type:</b> Recent | <b>Site:</b> {SITES.get(site)}</blockquote>"
            else:
                msg += f"\n<blockquote><b>Query:</b> <code>{key}</code> | <b>Site:</b> {SITES.get(site)}</blockquote>"
            search_results = search_results["data"]
        except Exception as e:
            await edit_message(message, f"<b>Error:</b> {str(e)}")
            return
    else:
        LOGGER.info(f"PLUGINS Searching: {key} from {site}")
        search_job = await TorrentManager.qbittorrent.search.start(
            pattern=key, plugins=[site], category="all"
        )
        search_id = search_job.id
        while True:
            result_status = await TorrentManager.qbittorrent.search.status(search_id)
            status = result_status[0].status
            if status != "Running":
                break
        dict_search_results = await TorrentManager.qbittorrent.search.results(
            id=search_id, limit=TELEGRAPH_LIMIT
        )
        search_results = dict_search_results.results
        total_results = dict_search_results.total
        if total_results == 0:
            await edit_message(
                message,
                f"<b>No results found for:</b> <code>{key}</code>\n<blockquote>Plugin Site: {site.capitalize()}</blockquote>",
            )
            return
        msg = f"<b>Found {min(total_results, TELEGRAPH_LIMIT)} result(s)</b>"
        msg += f"\n<blockquote><b>Query:</b> <code>{key}</code> | <b>Site:</b> {site.capitalize()}</blockquote>"
        await TorrentManager.qbittorrent.search.delete(search_id)
    link = await get_result(search_results, key, message, method)
    buttons = ButtonMaker()
    buttons.url_button("🔎 View Search Results", link, style=ButtonStyle.PRIMARY)
    button = buttons.build_menu(1)
    await edit_message(message, msg, button)


async def get_result(search_results, key, message, method):
    telegraph_content = []
    if method == "apirecent":
        msg = "<h4>API Recent Results</h4>"
    elif method == "apisearch":
        msg = f"<h4>API Search Results For {key}</h4>"
    elif method == "apitrend":
        msg = "<h4>API Trending Results</h4>"
    else:
        msg = f"<h4>Plugin Search Results For {key}</h4>"
    for index, result in enumerate(search_results, start=1):
        if method.startswith("api"):
            try:
                if "name" in result.keys():
                    msg += f"<code><a href='{result['url']}'>{escape(result['name'])}</a></code><br>"
                if "torrents" in result.keys():
                    for subres in result["torrents"]:
                        msg += f"<b>Quality: </b>{subres['quality']} | <b>Type: </b>{subres['type']} | "
                        msg += f"<b>Size: </b>{subres['size']}<br>"
                        if "torrent" in subres.keys():
                            msg += f"<a href='{subres['torrent']}'>Direct Link</a><br>"
                        elif "magnet" in subres.keys():
                            msg += "<b>Share Magnet: </b>"
                            msg += f"<a href='http://t.me/share/url?url={subres['magnet']}'>Telegram</a><br>"
                    msg += "<br>"
                else:
                    msg += f"<b>Size: </b>{result['size']}<br>"
                    try:
                        msg += f"<b>Seeders: </b>{result['seeders']} | <b>Leechers: </b>{result['leechers']}<br>"
                    except Exception:
                        pass
                    if "torrent" in result.keys():
                        msg += f"<a href='{result['torrent']}'>Direct Link</a><br><br>"
                    elif "magnet" in result.keys():
                        msg += "<b>Share Magnet: </b>"
                        msg += f"<a href='http://t.me/share/url?url={quote(result['magnet'])}'>Telegram</a><br><br>"
                    else:
                        msg += "<br>"
            except Exception:
                continue
        else:
            msg += f"<a href='{result.descrLink}'>{escape(result.fileName)}</a><br>"
            msg += f"<b>Size: </b>{get_readable_file_size(result.fileSize)}<br>"
            msg += f"<b>Seeders: </b>{result.nbSeeders} | <b>Leechers: </b>{result.nbLeechers}<br>"
            link = result.fileUrl
            if link.startswith("magnet:"):
                msg += f"<b>Share Magnet: </b><a href='http://t.me/share/url?url={quote(link)}'>Telegram</a><br><br>"
            else:
                msg += f"<a href='{link}'>Direct Link</a><br><br>"

        if len(msg.encode("utf-8")) > 39000:
            telegraph_content.append(msg)
            msg = ""

        if index == TELEGRAPH_LIMIT:
            break

    if msg != "":
        telegraph_content.append(msg)

    await edit_message(
        message, f"<b>Generating Telegraph results ({len(telegraph_content)} page/s)...</b>"
    )
    path = [
        (
            await telegraph.create_page(
                title="Torrent Search Results", content=content
            )
        )["path"]
        for content in telegraph_content
    ]
    if len(path) > 1:
        await edit_message(
            message, f"<b>Updating Telegraph results ({len(telegraph_content)} page/s)...</b>"
        )
        await telegraph.edit_telegraph(path, telegraph_content)
    return f"https://telegra.ph/{path[0]}"


def api_buttons(user_id, method):
    buttons = ButtonMaker()
    for data, name in SITES.items():
        buttons.data_button(name, f"torser {user_id} {data} {method}")
    buttons.data_button("Cancel", f"torser {user_id} cancel")
    return buttons.build_menu(2)


async def plugin_buttons(user_id):
    buttons = ButtonMaker()
    if not PLUGINS:
        pl = await TorrentManager.qbittorrent.search.plugins()
        for i in pl:
            PLUGINS.append(i.name)
    for siteName in PLUGINS:
        buttons.data_button(
            siteName.capitalize(), f"torser {user_id} {siteName} plugin"
        )
    buttons.data_button("All Sites", f"torser {user_id} all plugin")
    buttons.data_button("Cancel", f"torser {user_id} cancel")
    return buttons.build_menu(2)


@new_task
async def torrent_search(_, message):
    if Config.DISABLE_SEARCH:
        await send_message(
            message, "<blockquote>Torrent search is disabled by the owner.</blockquote>"
        )
        return
    user_id = message.from_user.id
    buttons = ButtonMaker()
    key = message.text.split()
    if SITES is None and not Config.SEARCH_PLUGINS:
        await send_message(
            message, "<blockquote>No Search API link or Plugins configured.</blockquote>"
        )
    elif len(key) == 1 and SITES is None:
        await send_message(message, "<blockquote>Send search keyword along with command.</blockquote>")
    elif len(key) == 1:
        buttons.data_button("🔥 Trending", f"torser {user_id} apitrend")
        buttons.data_button("🆕 Recent", f"torser {user_id} apirecent")
        buttons.data_button("❌ Cancel", f"torser {user_id} cancel")
        button = buttons.build_menu(2)
        await send_message(message, "<b>Select Search Mode:</b>", button)
    elif SITES is not None and Config.SEARCH_PLUGINS:
        buttons.data_button("🌐 API", f"torser {user_id} apisearch")
        buttons.data_button("🔌 Plugins", f"torser {user_id} plugin")
        buttons.data_button("❌ Cancel", f"torser {user_id} cancel")
        button = buttons.build_menu(2)
        await send_message(message, "<b>Select Search Engine:</b>", button)
    elif SITES is not None:
        button = api_buttons(user_id, "apisearch")
        await send_message(message, "<b>Select Search Site (API):</b>", button)
    else:
        button = await plugin_buttons(user_id)
        await send_message(message, "<b>Select Search Site (Plugins):</b>", button)


@new_task
async def torrent_search_update(_, query):
    user_id = query.from_user.id
    message = query.message
    key = message.reply_to_message.text.split(maxsplit=1)
    key = key[1].strip() if len(key) > 1 else None
    data = query.data.split()
    if user_id != int(data[1]):
        await query.answer("This menu is not for you!", show_alert=True)
    elif data[2].startswith("api"):
        await query.answer()
        button = api_buttons(user_id, data[2])
        await edit_message(message, "<b>Select Search Site:</b>", button)
    elif data[2] == "plugin":
        await query.answer()
        button = await plugin_buttons(user_id)
        await edit_message(message, "<b>Select Search Site:</b>", button)
    elif data[2] != "cancel":
        await query.answer()
        site = data[2]
        method = data[3]
        if method.startswith("api"):
            if key is None:
                if method == "apirecent":
                    endpoint = "Recent"
                elif method == "apitrend":
                    endpoint = "Trending"
                await edit_message(
                    message,
                    f"<b>Fetching {endpoint} torrents...</b>\n<blockquote>Site: {SITES.get(site)}</blockquote>",
                )
            else:
                await edit_message(
                    message,
                    f"<b>Searching for:</b> <code>{key}</code>\n<blockquote>Site: {SITES.get(site)}</blockquote>",
                )
        else:
            await edit_message(
                message,
                f"<b>Searching for:</b> <code>{key}</code>\n<blockquote>Site: {site.capitalize()}</blockquote>",
            )
        await search(key, site, message, method)
    else:
        await query.answer()
        await edit_message(message, "<b>Search process cancelled!</b>")
