# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSAssignmentStudentStatus(Document):
	def validate(self):
		# Ensure uniqueness: one status record per student per assignment
		if self.is_new():
			existing = frappe.db.exists(
				"LMS Assignment Student Status",
				{
					"assignment": self.assignment,
					"student": self.student,
					"name": ["!=", self.name]
				}
			)
			if existing:
				frappe.throw(f"Status record already exists for {self.student} on assignment {self.assignment}")

	def before_save(self):
		# Auto-update status based on submission if linked
		if self.submission:
			submission_doc = frappe.get_doc("LMS Assignment Submission", self.submission)

			# Map submission status to student status
			if submission_doc.status in ["Pass", "Fail"]:
				self.status = submission_doc.status
			elif submission_doc.status == "Not Graded":
				self.status = "Submitted"
			else:
				self.status = submission_doc.status


def create_student_status(assignment, student):
	"""
	Helper function to create a student status record.
	Called when an assignment is assigned to students.
	"""
	# Check if already exists
	existing = frappe.db.exists(
		"LMS Assignment Student Status",
		{"assignment": assignment, "student": student}
	)

	if not existing:
		status_doc = frappe.get_doc({
			"doctype": "LMS Assignment Student Status",
			"assignment": assignment,
			"student": student,
			"status": "Pending"
		})
		status_doc.insert(ignore_permissions=True)
		return status_doc.name
	return existing


def update_student_status(assignment, student, status, submission=None):
	"""
	Update student status for an assignment.

	Args:
		assignment: Assignment ID
		student: Student email
		status: New status value
		submission: Optional submission ID to link
	"""
	status_record = frappe.db.exists(
		"LMS Assignment Student Status",
		{"assignment": assignment, "student": student}
	)

	if status_record:
		doc = frappe.get_doc("LMS Assignment Student Status", status_record)
		doc.status = status
		if submission:
			doc.submission = submission
		doc.save(ignore_permissions=True)
	else:
		# Create new status record if it doesn't exist
		doc = frappe.get_doc({
			"doctype": "LMS Assignment Student Status",
			"assignment": assignment,
			"student": student,
			"status": status,
			"submission": submission
		})
		doc.insert(ignore_permissions=True)

	return doc.name


def get_student_status(assignment, student):
	"""
	Get the current status for a student on an assignment.

	Returns: dict with status info or None
	"""
	status_record = frappe.db.get_value(
		"LMS Assignment Student Status",
		{"assignment": assignment, "student": student},
		["name", "status", "submission", "last_viewed"],
		as_dict=True
	)

	return status_record


def mark_overdue_student_assignments():
	"""
	Scheduled job: Mark student assignments as Overdue if due date has passed
	and they haven't submitted yet.
	"""
	from frappe.utils import now_datetime, get_datetime

	try:
		now = now_datetime()

		# Get all Pending student statuses
		pending_statuses = frappe.get_all(
			"LMS Assignment Student Status",
			filters={"status": "Pending"},
			fields=["name", "assignment", "student"]
		)

		updated = 0
		for status_record in pending_statuses:
			# Get assignment due date
			due_date = frappe.db.get_value("LMS Assignment", status_record.assignment, "due_date")

			if due_date and now > get_datetime(due_date):
				# Mark as Overdue
				frappe.db.set_value(
					"LMS Assignment Student Status",
					status_record.name,
					"status",
					"Overdue",
					update_modified=False
				)
				updated += 1

		frappe.db.commit()
		frappe.logger().info(f"Marked {updated} student assignments as Overdue")

		return {"updated": updated}

	except Exception as e:
		frappe.log_error(f"mark_overdue_student_assignments: {e}", "Mark Overdue Scheduler Error")
		return {"updated": 0, "error": str(e)}
