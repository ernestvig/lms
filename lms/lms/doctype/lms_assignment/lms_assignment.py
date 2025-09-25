# Copyright (c) 2023, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from lms.lms.utils import has_course_instructor_role, has_course_moderator_role


class LMSAssignment(Document):
	pass


@frappe.whitelist()
def save_assignment(assignment, title, type, question):
	if not has_course_moderator_role() or not has_course_instructor_role():
		return

	if assignment:
		doc = frappe.get_doc("LMS Assignment", assignment)
	else:
		doc = frappe.get_doc({"doctype": "LMS Assignment"})

	doc.update({"title": title, "type": type, "question": question})
	doc.save(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def get_all_student_assignment(user, limit=None, **kwargs):
	"""
	Fetch all assignments where a given student is in the recipient list.
	"""

	# Step 1: Find all LMS Assignment IDs linked to this student
	student_links = frappe.get_all(
		"PL Students",
		filters={"students": user},
		fields=["parent"],
	)

	# Extract assignment IDs
	assignment_ids = [s.parent for s in student_links]

	if not assignment_ids:
		return []

	# Step 2: Fetch the assignments
	filters = {"name": ["in", assignment_ids]}
	filters.update(kwargs)
	user_assignments = frappe.get_all(
		"LMS Assignment",
		filters=filters,
		fields=["*"],
		limit=limit,
		order_by="creation desc",
	)

	return {"success": True, "data": user_assignments, "count": len(user_assignments)}


@frappe.whitelist()
def get_all_instructor_assignment(user, limit=None, **kwargs):
	"""
	Fetch all assignments created by a given instructor.
	"""

	# Step 1: Fetch the assignments
	filters = {"owner": user}
	filters.update(kwargs)
	instructor_assignments = frappe.get_all(
		"LMS Assignment",
		filters=filters,
		fields=["*"],
		limit=limit,
		order_by="creation desc",
	)

	return {"success": True, "data": instructor_assignments, "count": len(instructor_assignments)}
