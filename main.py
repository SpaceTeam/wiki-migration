from dataclasses import dataclass
from datetime import datetime
from functools import reduce
import json
import re
from textwrap import indent
from ascii import translate_to_ascii

import mysql.connector
import mwparserfromhell
import toml


@dataclass
class OldPage:
    """Page format as exported from mediawiki."""

    id: int
    title: str
    content: str
    timestamp: datetime
    last_user_email: str
    categories: list[str]


@dataclass
class NewPage:
    """Page format as needed for bookstack."""

    book_id: int
    name: str
    markdown: str
    tags: list[dict[str, str]]


def download_pages(config: dict) -> list[OldPage]:
    db = mysql.connector.connect(
        host=config["db_host"],
        user=config["db_user"],
        password=config["db_password"],
        database=config["db_database"],
    )

    query = open("pages.sql").read()

    cursor = db.cursor()
    cursor.execute(query)

    rows = cursor.fetchall()

    def mapper(row) -> OldPage:
        return OldPage(
            id=row[0],
            title=row[1].decode(),
            content=row[2].decode(),
            categories=[] if row[3] is None else row[3].decode().split(","),
            last_user_email=row[4].decode(),
            timestamp=datetime.strptime(row[5].decode(), "%Y%m%d%H%M%S"),
        )

    fileextensions = ["png", "jpeg", "jpg", "gif", "pdf"]

    iterator = map(mapper, rows)
    iterator = filter(
        lambda p: p.title.split(".")[-1].lower() not in fileextensions, iterator
    )
    pages = list(iterator)

    # print(rows[100])
    # print(mapper(rows[100]))
    # def printer(object):
    #     if isinstance(object, datetime):
    #         return object.isoformat()
    #     else:
    #         return object.__dict__

    # print(json.dumps(pages, indent=2, default=printer))

    return pages


def wikilink_to_slug(link: str) -> str:
    # Bookstack usses the php library: Illuminate\Support\Str and then calls
    # the slug method on it.
    # Here is a link to the php implementation I ported to python:
    # https://github.com/laravel/framework/blob/5.5/src/Illuminate/Support/Str.php#L414

    # Remove whitespaces and convert to lower
    link = link.strip().lower()

    # Translate to ascii
    link = translate_to_ascii(link)

    # Replace all underscores with dashes and all @ with ats
    link = link.replace("_", "-").replace("@", "at")

    # Replace all non character, seperator or digit characters
    link = re.sub(r"[^\-\s\da-z]+", "", link)

    # Replace whitespaces with seperator and multiple seperators with one
    link = re.sub(r"[\-\s]+", "-", link)

    return link


def process_page(config: dict, page: OldPage) -> NewPage:
    # Parse the mediawiki
    replace_list = {}
    wikicode = mwparserfromhell.parse(page.content)
    for node in wikicode.ifilter_wikilinks():
        # node.title = "BIG NERDZ"
        if ":" in node.title or "#" in node.title:
            continue

        new_link = "[" + config["bs_book_url"] + wikilink_to_slug(node.title) + "]"
        replace_list[str(node)] = new_link

    # Update the wikicode
    for old, new in replace_list.items():
        wikicode.replace(old, new)

    # Convert the wikicode into markdown with pandoc
    # TODO:

    # Create the tags
    tags = {c: "" for c in page.categories}
    tags.update(
        {
            "Letzter Author": page.last_user_email,
            "Zuletzt bearbeitet": page.timestamp.isoformat(),
        }
    )

    return NewPage(
        book_id=config["bs_book_id"],
        name=page.title,
        markdown=str(wikicode),
        tags=tags,
    )


def upload_pages(pages: list[NewPage]):
    # TODO: Upload to bookstack
    pass


def main():
    config = toml.loads(open("config.toml").read())

    print("Downloading... ")
    old_pages = download_pages(config)
    # print(
    #     json.dumps(
    #         process_page(config, old_pages[200]), indent=2, default=lambda p: p.__dict__
    #     )
    # )
    print("Processing... ")
    new_pages = list(map(lambda p: process_page(config, p), old_pages))

    # print("Uploading... ")
    # upload_pages(new_pages)


if __name__ == "__main__":
    main()
