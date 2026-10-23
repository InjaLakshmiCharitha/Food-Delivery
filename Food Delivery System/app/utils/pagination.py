from fastapi import Query
from sqlalchemy.orm import Query as SQLQuery


def paginate_query(
    query: SQLQuery,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    total = query.count()

    items = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "items": items,
    }