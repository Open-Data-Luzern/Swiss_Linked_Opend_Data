"""Der SQL-Guard: KI-generiertes SQL darf nur lesen, und nur die eine Tabelle."""

import sqlite3

import pytest

from swiss_portal.app import _ausfuehren, _sql_pruefen


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.execute("create table daten_x (datensammlung_id text, gemeinde text, wert real)")
    c.execute("create table geheim (x text)")
    c.executemany("insert into daten_x values ('s1', ?, ?)", [("Zug", 1.5), ("Baar", 2.5)])
    c.execute("insert into geheim values ('nein')")
    return c


@pytest.mark.parametrize("sql", [
    "select * from daten_x; drop table daten_x",
    "delete from daten_x",
    "pragma table_info(daten_x)",
    "attach database 'x.db' as y",
    "update daten_x set wert = 0",
    "with t as (select 1) insert into daten_x values (1,2,3)",
])
def test_verweigert_schreiben_und_mehrfachanweisungen(sql):
    with pytest.raises(ValueError):
        _sql_pruefen(sql)


def test_erlaubt_einfaches_select(db):
    sql = _sql_pruefen('select "gemeinde", "wert" from daten_x order by "wert" desc;')
    spalten, zeilen = _ausfuehren(db, "daten_x", sql)
    assert spalten == ["gemeinde", "wert"]
    assert zeilen == [["Baar", 2.5], ["Zug", 1.5]]


def test_verweigert_fremde_tabelle(db):
    sql = _sql_pruefen("select * from geheim")
    with pytest.raises(sqlite3.DatabaseError):
        _ausfuehren(db, "daten_x", sql)


def test_verweigert_fremde_tabelle_im_join(db):
    sql = _sql_pruefen("select d.gemeinde, g.x from daten_x d join geheim g")
    with pytest.raises(sqlite3.DatabaseError):
        _ausfuehren(db, "daten_x", sql)


def test_verweigert_katalogtabellen(db):
    sql = _sql_pruefen("select * from sqlite_master")
    with pytest.raises(sqlite3.DatabaseError):
        _ausfuehren(db, "daten_x", sql)


def test_begrenzt_zeilen(db):
    db.executemany("insert into daten_x values ('s1', 'G', ?)", [(i,) for i in range(2000)])
    _, zeilen = _ausfuehren(db, "daten_x", _sql_pruefen("select wert from daten_x"))
    assert len(zeilen) == 500
