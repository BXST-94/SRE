# -*- coding: utf-8 -*-
"""Crea amazon_electronics.sqlite a partir de sql/schema.sql y datos_iniciales/reviews_muestra.csv.

Uso (desde cualquier carpeta):  python actividad/crear_bd.py
Solo usa la biblioteca estandar y pandas.
"""
import os
import sqlite3
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(AQUI, "datos_iniciales", "reviews_muestra.csv")
SQL = os.path.join(AQUI, "sql", "schema.sql")
DB = os.path.join(AQUI, "amazon_electronics.sqlite")


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    with open(SQL, encoding="utf-8") as f:
        con.executescript(f.read())
    df = pd.read_csv(CSV)
    df["verified_purchase"] = df["verified_purchase"].astype(int)
    df.to_sql("reviews", con, if_exists="append", index=False)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    u = con.execute("SELECT COUNT(DISTINCT user_id) FROM reviews").fetchone()[0]
    con.close()
    print("reviews cargadas: %d | usuarios: %d | base: %s" % (n, u, DB))


if __name__ == "__main__":
    main()
