"""Тесты UI-виджетов."""

import tkinter as tk
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from test.conftest import gui_available
from ui.components import EntityCardGrid, EventTreeview

pytestmark = pytest.mark.skipif(
    not gui_available(), reason="Нет дисплея — GUI-тесты пропущены"
)


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    """Скрытое Tk-окно-хост для виджетов."""
    window = tk.Tk()
    window.withdraw()
    yield window
    window.destroy()


def _card_click(grid: EntityCardGrid, index: int) -> None:
    """Сгенерировать левый клик в центр карточки."""
    x1, y1, x2, _y2 = grid._card_rect(index)
    grid._on_click(SimpleNamespace(x=(x1 + x2) // 2, y=y1 + 10))


def test_card_click_toggles_status_and_updates_db(root, db) -> None:
    """Клик по карточке ТС переключает статус idle->arrived->departed."""
    db.add_vehicle("1234 АВ 7")
    grid = EntityCardGrid(root, db=db, entity_type="vehicle")
    grid.populate(db.get_vehicles())

    assert grid.row_count() == 1
    eid = db.get_vehicles()[0]["id"]
    assert grid._items[eid]["status"] == "idle"

    _card_click(grid, 0)

    assert db.find_vehicle_by_number("1234")["status"] == "arrived"
    assert grid._items[eid]["status"] == "arrived"

    _card_click(grid, 0)

    assert db.find_vehicle_by_number("1234")["status"] == "departed"
    assert grid._items[eid]["status"] == "departed"


def test_card_populate_sorts_by_name(root, db) -> None:
    """Карточки сортируются по имени независимо от порядка в БД."""
    db.add_vehicle("9 ТС")
    db.add_vehicle("1 ТС")
    db.add_vehicle("5555")

    grid = EntityCardGrid(root, db=db, entity_type="vehicle")
    grid.populate(db.get_vehicles())

    assert grid.row_count() == 3
    names = [grid._items[eid]["name"] for eid in grid._order]
    assert names == ["1 ТС", "5555", "9 ТС"]


def test_treeview_populates_event_rows(root, db) -> None:
    """Таблица журнала отображает события с подписями и тегами цветов."""
    db.add_vehicle("1234")
    vid = db.get_vehicles()[0]["id"]
    db.update_status_and_log("vehicle", vid, "1234", "arrived")

    tree = EventTreeview(root)
    tree.populate(db.recent_activity(10))

    children = tree._tree.get_children()
    assert len(children) == 2

    newest = tree._tree.item(children[0], "values")
    assert newest[1:] == ("ТС", "1234", "Прибыл")
    assert tree._tree.item(children[0], "tags") == ("arrived",)

    old = tree._tree.item(children[1], "values")
    assert old[3] == "Создан"
    assert tree._tree.item(children[1], "tags") == ("created",)
