# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSTag(Document):
	pass


@frappe.whitelist(allow_guest=True)
def get_all_tags():
    tags = frappe.get_all("LMS Tag", fields=["name", "tag_name"])
    return tags 