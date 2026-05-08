"""CLI to add a new institution to the database.

Usage:
    python scripts/create_institution.py \\
        --name "Madras Christian College (Autonomous)" \\
        --short-name "MCC" \\
        --domains "mcc.edu.in,students.mcc.edu.in" \\
        --address "Tambaram, Chennai – 600 059." \\
        --short-address "Tambaram, Chennai – 59" \\
        --university "University of Madras" \\
        --department "PG & Research Department of English" \\
        --aided

To upload a logo afterwards, use the admin UI or upload directly to R2 and
set institutions.logo_r2_key.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.institution import Institution


async def create_institution(
    *,
    name: str,
    short_name: str,
    domains: str,
    address: str,
    short_address: str,
    university: str,
    department: str,
    aided: bool,
) -> None:
    async with AsyncSessionLocal() as db:
        inst = Institution(
            name=name,
            short_name=short_name,
            email_domains=domains,
            address=address,
            short_address=short_address,
            university_name=university,
            default_department=department,
            department_aided=aided,
        )
        db.add(inst)
        await db.commit()
        await db.refresh(inst)
        print(f"Created institution: {inst.id}")
        print(f"  Name:    {inst.name}")
        print(f"  Domains: {inst.email_domains}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Add a new institution")
    parser.add_argument("--name", required=True)
    parser.add_argument("--short-name", required=True)
    parser.add_argument("--domains", required=True,
                        help="Comma-separated list of allowed email domains")
    parser.add_argument("--address", required=True)
    parser.add_argument("--short-address", required=True)
    parser.add_argument("--university", required=True)
    parser.add_argument("--department", required=True)
    parser.add_argument("--aided", action="store_true",
                        help="Add '(Aided)' marker on signature blocks")

    args = parser.parse_args()

    asyncio.run(create_institution(
        name=args.name,
        short_name=args.short_name,
        domains=args.domains,
        address=args.address,
        short_address=args.short_address,
        university=args.university,
        department=args.department,
        aided=args.aided,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
