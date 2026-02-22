"""Скрипт для заполнения базы данных командирами и автомобилями для нагрузочных тестов."""

import random
from database import Database


DATABASE_PATH = "database.db"
COUNT = 500

def generate_vehicle_numbers(count: int) -> list[str]:
    """Генерирует уникальные номера автомобилей."""
    numbers = []

    for i in range(1, count + 1):
        num = f"{random.randint(1000, 9999)}"
        numbers.append(num)

    return numbers


def generate_commander_names(count: int) -> list[str]:
    """Генерирует уникальные имена командиров."""
    first_names = [
        "Иван",
        "Пётр",
        "Александр",
        "Сергей",
        "Дмитрий",
        "Андрей",
        "Михаил",
        "Николай",
        "Владимир",
        "Евгений",
        "Олег",
        "Павел",
        "Виктор",
        "Юрий",
        "Борис",
        "Василий",
        "Геннадий",
        "Константин",
        "Леонид",
        "Михаил",
    ]
    last_names = [
        "Иванов",
        "Петров",
        "Сидоров",
        "Козлов",
        "Смирнов",
        "Васильев",
        "Попов",
        "Андреев",
        "Николаев",
        "Макаров",
        "Захаров",
        "Зайцев",
        "Соловьёв",
        "Кузнецов",
        "Михайлов",
        "Фёдоров",
        "Морозов",
        "Волков",
        "Алексеев",
        "Павлов",
    ]
    patronymics = [
        "Иванович",
        "Петрович",
        "Александрович",
        "Сергеевич",
        "Дмитриевич",
        "Андреевич",
        "Михайлович",
        "Николаевич",
        "Владимирович",
        "Евгеньевич",
    ]

    names = set()
    while len(names) < count:
        name = f"{random.choice(last_names)} {random.choice(first_names)} {random.choice(patronymics)}"
        names.add(name)

    return list(names)


def main():
    db = Database(path=DATABASE_PATH)

    # Генерируем данные
    vehicle_numbers = generate_vehicle_numbers(COUNT)
    commander_names = generate_commander_names(COUNT)

    # Добавляем автомобили
    print("Добавление автомобилей...")
    for number in vehicle_numbers:
        result = db.add_vehicle(number)
        if result:
            print(f"  Добавлен автомобиль: {number}")
        else:
            print(f"  Автомобиль {number} уже существует")

    # Добавляем командиров
    print("\nДобавление командиров...")
    for name in commander_names:
        result = db.add_commander(name)
        if result:
            print(f"  Добавлен командир: {name}")
        else:
            print(f"  Командир {name} уже существует")

    # Выводим статистику
    stats = db.stats()
    print(f"\nСтатистика базы данных:")
    print(f"  Автомобилей: {stats['vehicles']}")
    print(f"  Командиров: {stats['commanders']}")
    print(f"  Событий: {stats['total_events']}")


if __name__ == "__main__":
    main()
