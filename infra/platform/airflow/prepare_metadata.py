"""Create/verify only the dedicated metadata DB; run in a temporary private Pod."""

import os

import psycopg2
from psycopg2 import sql


def connect(user, password, database):
    return psycopg2.connect(
        host=os.environ["RDS_HOST"],
        dbname=database,
        user=user,
        password=password,
        sslmode="verify-full",
        sslrootcert="/opt/airflow/certs/global-bundle.pem",
        connect_timeout=15,
    )


def main():
    name = "airflow_meta"
    admin = connect(
        os.environ["RDS_ADMIN_USER"], os.environ["RDS_ADMIN_PASSWORD"], "postgres"
    )
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} CONNECTION LIMIT 16 "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                ).format(
                    sql.Identifier(name), sql.Literal(os.environ["AIRFLOW_DB_PASSWORD"])
                )
            )
        cur.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit "
            "FROM pg_roles WHERE rolname = %s",
            (name,),
        )
        assert cur.fetchone() == (False, False, False, False, 16)
        cur.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                sql.SQL(
                    "CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0"
                ).format(sql.Identifier(name), sql.Identifier(name))
            )
        else:
            assert row[0] == name, "Existing database owner needs review"
        cur.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(name)
            )
        )
        cur.execute("SELECT to_regclass('public.members')")
        if cur.fetchone()[0] is not None:
            cur.execute(
                "SELECT has_table_privilege(%s, 'public.members', 'SELECT')", (name,)
            )
            assert cur.fetchone()[0] is False
    admin.close()
    conn = connect(name, os.environ["AIRFLOW_DB_PASSWORD"], name)
    with conn, conn.cursor() as cur:
        cur.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        cur.execute(
            sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(sql.Identifier(name))
        )
        cur.execute("SELECT current_database(), current_user")
        assert cur.fetchone() == (name, name)
    conn.close()
    print("Dedicated metadata DB/user verified; business tables unchanged.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (psycopg2.Error, AssertionError, KeyError) as error:
        print("Metadata preparation failed: " + type(error).__name__, flush=True)
        raise SystemExit(1)
