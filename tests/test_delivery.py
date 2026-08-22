import inspect
import unittest
from datetime import datetime, timezone


class PickupServiceTests(unittest.TestCase):
    def test_codes_city_and_fields(self):
        from services.pickup_service import (
            format_pickup_code, normalize_pickup_code, validate_city,
            validate_pickup_address, validate_pickup_name, validate_pickup_note,
            validate_pickup_phone,
        )
        self.assertEqual(format_pickup_code(1), "PP000001")
        self.assertEqual(normalize_pickup_code(" pp000001 "), "PP000001")
        for city in ("dushanbe", "khujand"): self.assertEqual(validate_city(city), city)
        with self.assertRaises(ValueError): validate_city("other")
        self.assertEqual(validate_pickup_name(" Main Point "), "Main Point")
        self.assertEqual(validate_pickup_address(" Main street 1 "), "Main street 1")
        self.assertIsNone(validate_pickup_phone("/skip"))
        self.assertIsNone(validate_pickup_note("/skip"))
        for func, value in ((validate_pickup_name,"x"),(validate_pickup_address,"x"),
                            (validate_pickup_phone,"1"),(validate_pickup_note,"x")):
            with self.assertRaises(ValueError): func(value)

    def test_pickup_card_escapes_html(self):
        from services.pickup_service import format_pickup
        text=format_pickup({"pickup_code":"PP000001","city":"dushanbe","name":"<Main>",
                            "address":"<Address>","phone":None,"note":None,"is_active":True})
        self.assertIn("&lt;Main&gt;",text); self.assertNotIn("<Main>",text)


class DeliveryServiceTests(unittest.TestCase):
    def test_code_statuses_and_final(self):
        from services.delivery_service import (
            FinalDeliveryStatusError, DELIVERY_STATUSES, format_delivery_code,
            next_delivery_status, normalize_delivery_code,
        )
        self.assertEqual(format_delivery_code(1),"DL000001")
        self.assertEqual(normalize_delivery_code(" dl000001 "),"DL000001")
        self.assertEqual(next_delivery_status("assigned_pickup"),"domestic_transit")
        self.assertEqual(len(DELIVERY_STATUSES),4)
        with self.assertRaises(FinalDeliveryStatusError): next_delivery_status("ready_for_pickup")

    def test_note_and_client_privacy(self):
        from services.delivery_service import format_delivery, format_delivery_notification, validate_event_note
        self.assertIsNone(validate_event_note("/skip"))
        with self.assertRaises(ValueError): validate_event_note("x")
        row={"delivery_code":"DL000001","shipment_code":"SH000001","client_code":"C000001",
             "cargo_codes":["CG000001"],"consolidation_codes":[],"tracking_numbers":["TRACK1"],
             "status":"ready_for_pickup","pickup_city":"dushanbe","pickup_code":"PP000001",
             "pickup_name":"Main","pickup_address":"Address 1","pickup_phone":None,
             "assigned_at":datetime.now(timezone.utc),"ready_at":datetime.now(timezone.utc)}
        event={"to_status":"ready_for_pickup","occurred_at":datetime.now(timezone.utc),
               "created_by_telegram_id":999,"note":"internal"}
        client=format_delivery(row,[event]); admin=format_delivery({**row,"full_name":"A","client_phone":"12345"},[event],admin=True)
        self.assertNotIn("internal",client); self.assertNotIn("999",client)
        self.assertIn("internal",admin); self.assertIn("999",admin)
        notification=format_delivery_notification(row)
        self.assertIn("CG000001",notification); self.assertNotIn("internal",notification)


class DeliveryArchitectureTests(unittest.TestCase):
    def test_repository_transactions_and_scoped_updates(self):
        from repositories.deliveries import advance_delivery, create_delivery
        create_source=inspect.getsource(create_delivery)
        advance_source=inspect.getsource(advance_delivery)
        self.assertIn("transaction()",create_source)
        self.assertIn("_update_client_units",create_source)
        self.assertIn("FOR UPDATE",advance_source)
        self.assertIn("next_delivery_status(expected_from_status)",advance_source)

    def test_dispatcher_and_migration_order(self):
        from bot_app import create_dispatcher
        from migrations.runner import MIGRATIONS_DIR
        self.assertIn("include_router(delivery.router)",inspect.getsource(create_dispatcher))
        self.assertEqual([x.name for x in sorted(MIGRATIONS_DIR.glob("*.sql"))],
            ["001_create_orders.sql","002_create_clients.sql","003_create_china_trackings.sql",
             "004_create_cargos.sql","005_create_consolidations.sql","006_create_shipments.sql",
             "007_create_shipment_events.sql","008_create_pickup_deliveries.sql",
             "009_create_handovers_payments.sql"])


if __name__=="__main__": unittest.main()
