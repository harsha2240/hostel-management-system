import datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase


class DatabaseConfigurationTests(TestCase):
    """HMS-02: Django runs on MySQL 8 with the settings the SRS relies on."""

    def query_one(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchone()[0]

    def test_connects_to_mysql_8(self):
        self.assertEqual(connection.vendor, "mysql")
        self.assertFalse(connection.mysql_is_mariadb)
        self.assertGreaterEqual(connection.mysql_version, (8, 0))

    def test_sql_mode_keeps_mysql_8_safety_modes(self):
        sql_mode = set(self.query_one("SELECT @@SESSION.sql_mode").split(","))
        expected = {
            "ONLY_FULL_GROUP_BY",
            "STRICT_TRANS_TABLES",
            "NO_ZERO_IN_DATE",
            "NO_ZERO_DATE",
            "ERROR_FOR_DIVISION_BY_ZERO",
            "NO_ENGINE_SUBSTITUTION",
        }
        self.assertEqual(expected - sql_mode, set())

    def test_all_tables_use_innodb(self):
        # SRS 7: referential integrity through MySQL InnoDB.
        non_innodb = self.query_one(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND engine <> 'InnoDB'"
        )
        self.assertEqual(non_innodb, 0)

    def test_date_lookups_use_india_dates(self):
        # 20:00 UTC on 13 Oct is 01:30 IST on 14 Oct.
        get_user_model().objects.create_user(
            username="late-signup",
            date_joined=datetime.datetime(2026, 10, 13, 20, 0, tzinfo=datetime.UTC),
        )
        joined_on = get_user_model().objects.filter(
            date_joined__date=datetime.date(2026, 10, 14)
        )
        self.assertEqual(joined_on.count(), 1)
