# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSTag(Document):
	pass


@frappe.whitelist()
def get_all_tags(limit=None):
    tags = frappe.get_all("LMSTag", fields=["name", "tag_name"], limit=limit)
    return tags
