"""Public pages, the contact form and the newsletter."""
from earthscape.crypto import decrypt
from earthscape.db import db
from earthscape.testing import MongoTestCase

from .pages import PLANS, POSTS, SERVICES

PAGES = ["/", "/about/", "/services/", "/pricing/", "/blog/", "/contact/", "/privacy-policy/",
         "/changelog/", "/licenses/", "/style-guide/"]
MESSAGE = {"name": "Sara", "email": "Sara@Test.example", "message": "Hello there"}


#----------------------------pages--------------------------------------

class PageTests(MongoTestCase):
    with_users = False

    def test_every_page_loads_with_nav_and_footer(self):
        for path in PAGES:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="footer"')
                self.assertNotContains(response, "webflow")
                self.assertNotContains(response, "data-wf-")

    def test_every_detail_page_loads(self):
        for folder, registry in (("services", SERVICES), ("pricing", PLANS), ("blog", POSTS)):
            for slug in registry:
                with self.subTest(slug=slug):
                    self.assertEqual(self.client.get("/%s/%s/" % (folder, slug)).status_code, 200)

    def test_nav_marks_the_current_page(self):
        about = self.client.get("/about/").content.decode()
        self.assertRegex(about, r'href="/about/"[^>]*is-current|is-current[^>]*href="/about/"')

    def test_pricing_shows_each_plan_card(self):
        page = self.client.get("/pricing/")
        self.assertEqual(len(page.context["plans"]), 3)
        for plan in page.context["plans"]:
            self.assertContains(page, plan["title"])

    def test_unknown_pages_get_the_404_page(self):
        for path in ("/blog/not-a-post/", "/services/nothing/", "/no-such-page/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    def test_old_webflow_links_redirect(self):
        response = self.client.get("/about.html")
        self.assertEqual((response.status_code, response["Location"]), (301, "/about/"))
        self.assertEqual(self.client.get("/dashboard.html")["Location"], "/dashboard/")
        self.assertEqual(self.client.get("/missing.html").status_code, 404)

    def test_static_files_are_served_but_not_outside_the_folders(self):
        self.assertEqual(self.client.get("/static/website/website.css").status_code, 200)
        # Refused, never served
        self.assertIn(self.client.get("/static/../earthscape/settings.py").status_code, (400, 404))


#----------------------------contact form--------------------------------------

class ContactTests(MongoTestCase):

    def test_message_is_stored_encrypted_and_the_admin_is_told(self):
        response = self.client.post("/contact/", MESSAGE)
        self.assertIn("Thank you", self.follow_messages(response)[0])
        stored = db.contact_messages.find_one()
        self.assertNotIn("Hello there", str(stored))
        self.assertEqual(decrypt(stored["message_enc"]), "Hello there")
        self.assertEqual(decrypt(stored["email_enc"]), "sara@test.example")
        self.assertIn("New message from Sara", db.notifications.find_one({"user_id": str(self.admin_id)})["text"])

    def test_bad_messages_are_refused_and_keep_what_was_typed(self):
        for changes in ({"email": "nope"}, {"name": ""}, {"message": "  "}):
            response = self.client.post("/contact/", dict(MESSAGE, **changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form_errors"], changes)
            self.assertContains(response, 'class="site-message is-error"')
        self.assertContains(self.client.post("/contact/", dict(MESSAGE, email="nope")), 'value="Sara"')
        self.assertEqual(db.contact_messages.count_documents({}), 0)

    def test_one_address_can_only_send_a_few_an_hour(self):
        for _ in range(5):
            self.client.post("/contact/", MESSAGE)
        response = self.client.post("/contact/", MESSAGE)
        self.assertIn("Too many", response.context["form_errors"][0])
        self.assertEqual(db.contact_messages.count_documents({}), 5)


#----------------------------newsletter--------------------------------------

class NewsletterTests(MongoTestCase):
    with_users = False

    def test_sign_up_is_stored_once_and_goes_back_to_the_page(self):
        first = self.client.post("/newsletter/", {"email": "a@test.example", "next": "/about/"})
        self.assertEqual(first["Location"], "/about/#footer")
        self.client.post("/newsletter/", {"email": "A@test.example", "next": "/about/"})
        self.assertEqual(db.newsletter.count_documents({}), 1)
        self.assertNotIn("a@test.example", str(db.newsletter.find_one()))

    def test_bad_email_and_off_site_return_are_refused(self):
        response = self.client.post("/newsletter/", {"email": "nope", "next": "https://evil.example/"})
        self.assertEqual(response["Location"], "/#footer")
        self.assertEqual(db.newsletter.count_documents({}), 0)

    def test_newsletter_needs_a_post(self):
        self.assertEqual(self.client.get("/newsletter/").status_code, 405)
