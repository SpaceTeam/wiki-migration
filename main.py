from dataclasses import dataclass
from datetime import datetime
from functools import reduce
import json

import mysql.connector
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


def process_pages(pages: list[OldPage]) -> list[NewPage]:
    pass


def upload_pages(pages: list[NewPage]):
    pass


def main():
    config = toml.loads(open("config.toml").read())
    old_pages = download_pages(config)
    new_pages = process_pages(old_pages)
    upload_pages(new_pages)

    print(reduce(lambda p1, p2: p1 if p1.timestamp < p2.timestamp else p2, pages))


if __name__ == "__main__":
    main()
