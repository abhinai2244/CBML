from html.entities import name2codepoint
from html.parser import HTMLParser
from json import dumps as jdumps
from re import compile as re_compile

from niquests import AsyncSession


_RE_WHITESPACE = re_compile(r"(\s+)")

_ALLOWED_TAGS = {
    "a",
    "aside",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "figcaption",
    "figure",
    "h3",
    "h4",
    "hr",
    "i",
    "iframe",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "strong",
    "u",
    "ul",
    "video",
}

_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "keygen",
    "link",
    "menuitem",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

_BLOCK_ELEMENTS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "canvas",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "li",
    "main",
    "nav",
    "noscript",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tfoot",
    "ul",
    "video",
}


class TelegraphError(Exception):
    pass


class NotAllowedTag(TelegraphError):
    pass


class InvalidHTML(TelegraphError):
    pass


class RetryAfterError(TelegraphError):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__(f"Flood control, retry in {retry_after}s")


class _HTMLToNodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self._current = self.nodes
        self._parents = []
        self._last_text = None
        self._tags = []

    def _add_text(self, s):
        if not s:
            return
        if "pre" not in self._tags:
            s = _RE_WHITESPACE.sub(" ", s)
            if self._last_text is None or self._last_text.endswith(" "):
                s = s.lstrip(" ")
            if not s:
                self._last_text = None
                return
            self._last_text = s
        if self._current and isinstance(self._current[-1], str):
            self._current[-1] += s
        else:
            self._current.append(s)

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_TAGS:
            raise NotAllowedTag(f"<{tag}> not allowed")
        if tag in _BLOCK_ELEMENTS:
            self._last_text = None
        node = {"tag": tag}
        self._tags.append(tag)
        self._current.append(node)
        if attrs:
            node["attrs"] = dict(attrs)
        if tag not in _VOID_ELEMENTS:
            self._parents.append(self._current)
            self._current = node["children"] = []

    def handle_endtag(self, tag):
        if tag in _VOID_ELEMENTS:
            return
        if not self._parents:
            raise InvalidHTML(f"</{tag}> missing start tag")
        self._current = self._parents.pop()
        last = self._current[-1]
        if last["tag"] != tag:
            raise InvalidHTML(f"</{tag}> closed instead of </{last['tag']}>")
        self._tags.pop()
        if not last.get("children"):
            last.pop("children", None)

    def handle_data(self, data):
        self._add_text(data)

    def handle_entityref(self, name):
        self._add_text(chr(name2codepoint[name]))

    def handle_charref(self, name):
        self._add_text(
            chr(int(name[1:], 16)) if name.startswith("x") else chr(int(name))
        )

    def get_nodes(self):
        if self._parents:
            raise InvalidHTML(f"<{self._parents[-1][-1]['tag']}> not closed")
        return self.nodes


def html_to_nodes(html):
    parser = _HTMLToNodes()
    parser.feed(html)
    return parser.get_nodes()


def _j(data):
    return jdumps(data, separators=(",", ":"), ensure_ascii=False)


class Telegraph:
    __slots__ = ("access_token", "domain", "session")

    def __init__(self, access_token=None, domain="graph.org"):
        self.access_token = access_token
        self.domain = domain
        self.session = AsyncSession()
        self.session.headers.update(
            {"Content-Type": "application/x-www-form-urlencoded"}
        )

    async def _method(self, method, values=None, path=""):
        values = dict(values or {})
        if "access_token" not in values and self.access_token:
            values["access_token"] = self.access_token
        resp = await self.session.post(
            f"https://api.{self.domain}/{method}/{path}", data=values
        )
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        error = data.get("error")
        if isinstance(error, str) and error.startswith("FLOOD_WAIT_"):
            raise RetryAfterError(int(error.rsplit("_", 1)[-1]))
        raise TelegraphError(error)

    async def create_account(self, short_name, author_name=None, author_url=None):
        resp = await self._method(
            "createAccount",
            {
                "short_name": short_name,
                "author_name": author_name,
                "author_url": author_url,
            },
        )
        self.access_token = resp.get("access_token")
        return resp

    async def create_page(self, title, html_content, author_name=None, author_url=None):
        content = _j(html_to_nodes(html_content))
        return await self._method(
            "createPage",
            {
                "title": title,
                "author_name": author_name,
                "author_url": author_url,
                "content": content,
            },
        )

    async def edit_page(
        self, path, title, html_content, author_name=None, author_url=None
    ):
        content = _j(html_to_nodes(html_content))
        return await self._method(
            "editPage",
            values={
                "title": title,
                "author_name": author_name,
                "author_url": author_url,
                "content": content,
            },
            path=path,
        )


