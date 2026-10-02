"""360 derece müşteri/çalışan profili için hedefli, elle yazılmış sorgular çalıştırır."""
from typing import Optional

from db_repository import DatabaseRepository
from models import CustomerProfile, EmployeeProfile


class ProfileRepository:
    def __init__(self, db_repository: DatabaseRepository):
        self._db = db_repository

    def find_customer_profile(self, customer_name: str) -> Optional[CustomerProfile]:
        customer_result = self._db.run_select_query(
            "SELECT TOP 1 id, full_name, city, phone, registration_date "
            "FROM customers WHERE full_name LIKE :name",
            {"name": f"%{customer_name}%"},
        )
        if customer_result.is_empty():
            return None
        customer_row = customer_result.rows[0]
        customer_id = customer_row[0]

        orders = self._db.run_select_query(
            "SELECT id, order_date, total_amount, status FROM orders "
            "WHERE customer_id = :cid ORDER BY order_date DESC",
            {"cid": customer_id},
        ).rows

        top_products = self._db.run_select_query(
            "SELECT p.product_name, SUM(oi.quantity) AS total_quantity "
            "FROM order_items oi "
            "JOIN orders o ON oi.order_id = o.id "
            "JOIN products p ON oi.product_id = p.id "
            "WHERE o.customer_id = :cid "
            "GROUP BY p.product_name ORDER BY total_quantity DESC",
            {"cid": customer_id},
        ).rows

        account_result = self._db.run_select_query(
            "SELECT title, tax_number, currency FROM customer_accounts WHERE customer_id = :cid",
            {"cid": customer_id},
        )
        account_card = account_result.rows[0] if not account_result.is_empty() else None

        shipments = self._db.run_select_query(
            "SELECT o.id, s.carrier, s.status, s.ship_date, s.delivery_date "
            "FROM shipments s JOIN orders o ON s.order_id = o.id "
            "WHERE o.customer_id = :cid ORDER BY s.ship_date DESC",
            {"cid": customer_id},
        ).rows

        return CustomerProfile(
            customer_row=customer_row,
            orders=orders,
            top_products=top_products,
            account_card=account_card,
            shipments=shipments,
        )

    def find_employee_profile(self, employee_name: str) -> Optional[EmployeeProfile]:
        employee_result = self._db.run_select_query(
            "SELECT TOP 1 id, full_name, department, title, hire_date, city "
            "FROM employees WHERE full_name LIKE :name",
            {"name": f"%{employee_name}%"},
        )
        if employee_result.is_empty():
            return None
        employee_row = employee_result.rows[0]
        employee_id = employee_row[0]

        izin_talepleri = self._db.run_select_query(
            "SELECT start_date, end_date, leave_type, status "
            "FROM employee_leave WHERE employee_id = :cid "
            "ORDER BY start_date DESC",
            {"cid": employee_id},
        ).rows

        performans_kayitlari = self._db.run_select_query(
            "SELECT review_date, score, comment FROM employee_performance "
            "WHERE employee_id = :cid ORDER BY review_date DESC",
            {"cid": employee_id},
        ).rows

        tamamlanan_egitimler = self._db.run_select_query(
            "SELECT t.training_name, et.completion_date, et.result "
            "FROM employee_trainings et JOIN trainings t ON et.training_id = t.id "
            "WHERE et.employee_id = :cid ORDER BY et.completion_date DESC",
            {"cid": employee_id},
        ).rows

        return EmployeeProfile(
            employee_row=employee_row,
            izin_talepleri=izin_talepleri,
            performans_kayitlari=performans_kayitlari,
            tamamlanan_egitimler=tamamlanan_egitimler,
        )
