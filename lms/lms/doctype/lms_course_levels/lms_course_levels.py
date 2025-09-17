# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document


class LMSCourseLevels(Document):
	pass

@frappe.whitelist(allow_guest=True)
def get_all_course_levels():
	course_levels = frappe.get_all("LMS Course Levels", fields=["name", "education_level"])
	return course_levels
