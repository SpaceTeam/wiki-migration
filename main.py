import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import re
import subprocess
from textwrap import indent
from urllib import request
from ascii import translate_to_ascii

import mysql.connector
import mwparserfromhell
import requests
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
    html: str
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

    return list(map(mapper, rows))


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


def mediawiki_to_html(content: str) -> str:
    proc = subprocess.run(
        [
            "pandoc",
            "-f",
            "mediawiki",
            "-t",
            "html",
        ],
        input=content.encode(),
        capture_output=True,
    )
    return proc.stdout.decode()


def find_similar_file(name: str) -> str:
    """
    Since MediaWiki is not casesensitive with filenames we might have a
    misspelled filename here so we try to find a file that loosley matches our
    filename.
    """

    for root, dirs, files in os.walk("images"):
        for file in files:
            if file.lower() == name.lower():
                return os.path.join(root, file)

    raise Exception(f"Unable to find file '{name}'")


def load_image_base64(name: str) -> str:
    # filenames replace spaces with underscore
    name = name.strip().replace(" ", "_")

    # Yes you are right some filenames have a f*cking invisible unicode
    # character in them. WikiMedia accepts that so we need too.
    name = name.replace("\u200E", "")

    # Hash the filename with md5
    hash = hashlib.md5(name.encode()).hexdigest()

    # This is cursed!
    # But apperently MediaWiki does it so we have to do it too
    # And yes the hash gets calculated on the original name but thats not what
    # is acutally stored then.
    umlaute = "üÜäÄöÖ"
    for c in umlaute:
        name = name.replace(c, "�")

    # Open the file
    path = os.path.join("images", hash[0], hash[:2], name)
    if not os.path.exists(path):
        path = find_similar_file(name)

    with open(path, "rb") as image:
        content = base64.b64encode(image.read()).decode()

    if name.lower().endswith("png"):
        return "data:image/png;base64," + content
    elif name.lower().endswith("jpg") or name.lower().endswith("jpeg"):
        return "data:image/jpeg;base64," + content
    elif name.lower().endswith("gif"):
        return "data:image/gif;base64," + content
    else:
        raise Exception(f"Unsupported inline image: {name.lower().split('.')[-1]}")


def process_page(config: dict, page: OldPage) -> NewPage:
    print(f"🤖 Processing page [{page.id}] {page.title}")

    # Parse the mediawiki
    replace_list = {}
    wikicode = mwparserfromhell.parse(page.content)
    for node in wikicode.ifilter_wikilinks():
        if ":" not in node.title and "#" not in node.title:
            new_text = str(node.text) if node.text else str(node.title)
            new_link = (
                "["
                + config["bs_book_url"]
                + wikilink_to_slug(node.title)
                + " "
                + new_text
                + "]"
            )
            replace_list[str(node)] = new_link

        elif re.match(r":?(Datei|File):", str(node.title)):
            filename = node.title.split(":")[-1]
            try:
                new_img = f"[[File:{load_image_base64(filename)}|{filename}]]"
                replace_list[str(node)] = new_img
            except Exception as e:
                print("⚠️ " + str(e))

    # Update the wikicode
    for old, new in replace_list.items():
        try:
            wikicode.replace(old, new)
        except Exception as e:
            print("⚠️ " + str(e))

    # Convert the wikicode into html with pandoc
    html = mediawiki_to_html(str(wikicode))

    # Create the tags
    tags = {c: "" for c in page.categories}
    tags.update(
        {
            "Letzter Author": page.last_user_email,
            "Zuletzt bearbeitet": page.timestamp.strftime("%Y-%d-%m %H:%M:%S"),
        }
    )

    return NewPage(
        book_id=config["bs_book_id"],
        name=page.title.replace("_", " "),
        html=html,
        tags=tags,
    )


def upload_pages(config: dict, pages: list[NewPage]):
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Token {config['bs_token_id']}:{config['bs_token_secret']}",
        }
    )

    for i, page in enumerate(pages):
        print(f"⬆️ [{i+1}/{len(pages)}] Upload page {page.name}")

        r = session.post(
            config["bs_api_url"] + "pages",
            json={
                "book_id": page.book_id,
                "name": page.name,
                "html": page.html,
                "tags": [{"name": k, "value": v} for k, v in page.tags.items()],
            },
        )
        if r.status_code != 200:
            print(f"🔥 Status code was: {r.status_code}")
            print(r.text)


def main():
    config = toml.loads(open("config.toml").read())

    print("Downloading... ")
    old_pages = download_pages(config)
    # old_pages = old_pages[50:60]
    # print(
    #     json.dumps(
    #         process_page(config, old_pages[200]), indent=2, default=lambda p: p.__dict__
    #     )
    # )
    print("Processing... ")

    new_pages = list(map(lambda p: process_page(config, p), old_pages))

    with open("cache.json", "w") as f:
        f.write(json.dumps(new_pages, indent=2, default=lambda p: p.__dict__))

    # print(json.dumps(new_pages[200], indent=2, default=lambda p: p.__dict__))
    # print("Uploading... ")
    upload_pages(config, new_pages)


if __name__ == "__main__":
    main()
