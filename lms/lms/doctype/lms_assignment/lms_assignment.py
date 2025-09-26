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

	result = []
	for a in user_assignments:
		quiz_questions = frappe.get_all(
			"LMS Quiz Question",
			filters={"parent": a.get("name"), "parenttype": "LMS Assignment"},
			fields=[
				"name",
				"question",
				"question_type",
				"marks",
				"option_a",
				"option_b",
				"option_c",
				"option_d",
				"correct_answer",
				"explanation",
			],
		)

		result.append(
			{
				"id": a.get("name"),
				"title": a.get("title"),
				"type": a.get("type"),
				"question": a.get("question"),
				"created_at": a.get("creation"),
				"description": a.get("instructions") or a.get("description"),
				"file": a.get("file"),
				"resource_link": a.get("resource_link"),
				"show_answers": a.get("show_answers"),
				"due_date": a.get("due_date"),
				"total_marks": a.get("total_score"),
				"submitted": a.get("submitted"),
				"drafted": a.get("drafted"),
				"grade_assignment": a.get("grade_assignment"),
				"is_public": a.get("public"),
				"quiz_questions": [
					{
						"id": q.get("name"),
						"question": q.get("question"),
						"question_type": q.get("question_type"),
						"options": q.get("options"),
						"correct_answer": q.get("correct_answer"),
						"marks": q.get("marks"),
						"option_a": q.get("option_a"),
						"option_b": q.get("option_b"),
						"option_c": q.get("option_c"),
						"option_d": q.get("option_d"),
						"explanation": q.get("explanation"),
					}
					for q in quiz_questions
				],
				"subject": (
					{
						"id": a.get("subject"),
						"subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
					}
					if a.get("subject")
					else None
				),
				"educational_level": (
					{
						"id": a.get("educational_level"),
						"educational_level": frappe.db.get_value(
							"LMS Course Levels", a.get("educational_level"), "education_level"
						),
					}
					if a.get("educational_level")
					else None
				),
			}
		)

	return [
		{
			"success": True,
			"message": "Assignments fetched successfully",
			"data": result,
		}
	]


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


@frappe.whitelist(allow_guest=True)
def get_assignment_details(assignment):
	assignments = frappe.get_all(
		"LMS Assignment",
		filters={"name": assignment},
		fields=["*"],
	)

	if not assignments:
		return {"success": False, "message": "Assignment not found"}

	result = []
	for a in assignments:
		quiz_questions = frappe.get_all(
			"LMS Quiz Question",
			filters={"parent": a.get("name"), "parenttype": "LMS Assignment"},
			fields=[
				"name",
				"question",
				"question_type",
				"marks",
				"option_a",
				"option_b",
				"option_c",
				"option_d",
				"correct_answer",
				"explanation",
			],
		)

		result.append(
			{
				"id": a.get("name"),
				"title": a.get("title"),
				"type": a.get("type"),
				"question": a.get("question"),
				"created_at": a.get("creation"),
				"description": a.get("instructions") or a.get("description"),
				"file": a.get("file"),
				"resource_link": a.get("resource_link"),
				"show_answers": a.get("show_answers"),
				"due_date": a.get("due_date"),
				"total_marks": a.get("total_score"),
				"submitted": a.get("submitted"),
				"drafted": a.get("drafted"),
				"grade_assignment": a.get("grade_assignment"),
				"is_public": a.get("public"),
				"quiz_questions": [
					{
						"id": q.get("name"),
						"question": q.get("question"),
						"question_type": q.get("question_type"),
						"marks": q.get("marks"),
						"option_a": q.get("option_a"),
						"option_b": q.get("option_b"),
						"option_c": q.get("option_c"),
						"option_d": q.get("option_d"),
						"correct_answer": q.get("correct_answer"),
						"explanation": q.get("explanation"),
					}
					for q in quiz_questions
				],
				"subject": (
					{
						"id": a.get("subject"),
						"subject_name": frappe.db.get_value("Subject", a.get("subject"), "subject_name"),
					}
					if a.get("subject")
					else None
				),
				"educational_level": (
					{
						"id": a.get("educational_level"),
						"educational_level": frappe.db.get_value(
							"LMS Course Levels", a.get("educational_level"), "education_level"
						),
					}
					if a.get("educational_level")
					else None
				),
			}
		)

	return [
		{
			"success": True,
			"message": "Assignments fetched successfully",
			"data": result,
		}
	]
