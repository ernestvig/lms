# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

from re import sub

import frappe
from frappe import _
from frappe.model.document import Document


class LMSPastQuestions(Document):
	def validate(self):
		self.validate_payment_app()

	def validate_payment_app(self):
		if self.paid_past_question:
			installed_apps = frappe.get_installed_apps()
			if "payments" not in installed_apps:
				documentation_link = "https://docs.frappe.io/learning/setting-up-payment-gateway"
				frappe.throw(
					_(
						"Please install the 'payments' app to enable this feature. Refer to the documentation: {0}"
					).format(documentation_link)
				)


@frappe.whitelist(allow_guest=True)
def get_tutor_past_questions(tutor):
	past_questions = frappe.get_all(
		"LMS Past Questions",
		filters={"owner": tutor},
		fields=[
			"name",
			"title",
			"subject",
			"paid_past_question",
			"amount",
			"file",
			"amount_usd",
			"drafted",
			"public",
			"exam_type",
			"question_type",
			"academic_year",
			"student_link",
			"currency",
			"enable_comment",
			"description",
			"category",
			"educational_level",
			"download_count"
		],
	)

	return {
		"success": True,
		"past_questions": [
			{
				"Doctype": "LMS Past Questions",
				"id": q["name"],
				"title": q.get("title"),
				"drafted": q.get("drafted"),
				"public": q.get("public"),
				"exam_type": q.get("exam_type"),
				"question_type": q.get("question_type"),
				"academic_year": q.get("academic_year"),
				"student_link": q.get("student_link"),
				"paid_past_question": q.get("paid_past_question"),
				"amount": q.get("amount"),
				"currency": q.get("currency"),
				"enable_comment": q.get("enable_comment"),
				"amount_usd": q.get("amount_usd"),
				"file_url": q.get("file"),
				"description": q.get("description"),
				"download_count": q.get("download_count") or 0,
				"educational_level": (
					{
						"id": q.get("educational_level"),
						"level_name": frappe.db.get_value(
							"LMS Course Level", q.get("educational_level"), "education_level"
						),
					}
					if q.get("educational_level")
					else None
				),
				"subject": (
					{
						"id": q.get("subject"),
						"subject_name": frappe.db.get_value("Subject", q.get("subject"), "subject_name"),
					}
					if q.get("subject")
					else None
				),
				"category": (
					{
						"id": q.get("category"),
						"category_name": frappe.db.get_value("LMS Category", q.get("category"), "category"),
					}
					if q.get("category")
					else None
				),
			}
			for q in past_questions
		],
	}


@frappe.whitelist(allow_guest=True)
def get_all_past_questions():
	past_questions = frappe.get_all(
		"LMS Past Questions",
		fields=[
			"name",
			"title",
			"subject",
			"paid_past_question",
			"amount",
			"file",
			"amount_usd",
			"drafted",
			"public",
			"exam_type",
			"question_type",
			"academic_year",
			"student_link",
			"currency",
			"enable_comment",
			"description",
			"category",
			"educational_level",
			"download_count",
		],
	)

	return {
		"success": True,
		"past_questions": [
			{
				"Doctype": "LMS Past Questions",
				"id": q["name"],
				"title": q.get("title"),
				"drafted": q.get("drafted"),
				"public": q.get("public"),
				"exam_type": q.get("exam_type"),
				"question_type": q.get("question_type"),
				"academic_year": q.get("academic_year"),
				"student_link": q.get("student_link"),
				"paid_past_question": q.get("paid_past_question"),
				"amount": q.get("amount"),
				"currency": q.get("currency"),
				"enable_comment": q.get("enable_comment"),
				"amount_usd": q.get("amount_usd"),
				"file_url": q.get("file"),
				"description": q.get("description"),
				"download_count": q.get("download_count") or 0,
				"educational_level": (
					{
						"id": q.get("educational_level"),
						"level_name": frappe.db.get_value(
							"LMS Course Level", q.get("educational_level"), "education_level"
						),
					}
					if q.get("educational_level")
					else None
				),
				"subject": (
					{
						"id": q.get("subject"),
						"subject_name": frappe.db.get_value("Subject", q.get("subject"), "subject_name"),
					}
					if q.get("subject")
					else None
				),
				"category": (
					{
						"id": q.get("category"),
						"category_name": frappe.db.get_value("LMS Category", q.get("category"), "category"),
					}
					if q.get("category")
					else None
				),
			}
			for q in past_questions
		],
	}


@frappe.whitelist(allow_guest=True)
def get_past_question_details(past_question):
	past_questions = frappe.get_all(
		"LMS Past Questions",
		filters={"name": past_question},
		fields=[
			"name",
			"title",
			"subject",
			"paid_past_question",
			"amount",
			"file",
			"amount_usd",
			"drafted",
			"public",
			"exam_type",
			"question_type",
			"academic_year",
			"student_link",
			"currency",
			"enable_comment",
			"description",
			"category",
			"educational_level",
			"download_count"
		],
	)

	return {
		"success": True,
		"past_questions": [
			{
				"Doctype": "LMS Past Questions",
				"id": q["name"],
				"title": q.get("title"),
				"drafted": q.get("drafted"),
				"public": q.get("public"),
				"exam_type": q.get("exam_type"),
				"question_type": q.get("question_type"),
				"academic_year": q.get("academic_year"),
				"student_link": q.get("student_link"),
				"paid_past_question": q.get("paid_past_question"),
				"amount": q.get("amount"),
				"currency": q.get("currency"),
				"enable_comment": q.get("enable_comment"),
				"amount_usd": q.get("amount_usd"),
				"file_url": q.get("file"),
				"description": q.get("description"),
				"download_count": q.get("download_count") or 0,
				"educational_level": (
					{
						"id": q.get("educational_level"),
						"level_name": frappe.db.get_value(
							"LMS Course Level", q.get("educational_level"), "education_level"
						),
					}
					if q.get("educational_level")
					else None
				),
				"subject": (
					{
						"id": q.get("subject"),
						"subject_name": frappe.db.get_value("Subject", q.get("subject"), "subject_name"),
					}
					if q.get("subject")
					else None
				),
				"category": (
					{
						"id": q.get("category"),
						"category_name": frappe.db.get_value("LMS Category", q.get("category"), "category"),
					}
					if q.get("category")
					else None
				),
				"comments": (
					{
						"id": q.get("comments"),
						"comment": frappe.db.get_value("Past Question Comment", q.get("comments"), "comment"),
					}
					if q.get("comments")
					else None
				),
			}
			for q in past_questions
		],
	}


@frappe.whitelist(allow_guest=True)
def get_past_question_count_kpi(tutor):
	public_questions = frappe.get_all(
		"LMS Past Questions", filters={"owner": tutor, "public": 1, "drafted": 0}, fields=["student_link"]
	)
	public_questions_count = len(public_questions)

	# Collect all student links (assuming student_link is a user id or similar)
	student_links = [q["student_link"] for q in public_questions if q.get("student_link")]
	unique_students = set(student_links)
	student_demographics_count = len(unique_students)

	return {
		"success": True,
		"published_questions": public_questions_count,
		"student_demographics": student_demographics_count,
		"total_earnings": "GHS 0",
	}

@frappe.whitelist()
def increase_download_count(past_question):
	if not past_question:
		return {"success": False, "message": "Past question ID is required."}

	try:
		pq_doc = frappe.get_doc("LMS Past Questions", past_question)
		pq_doc.download_count = (pq_doc.download_count or 0) + 1
		pq_doc.save(ignore_permissions=True,)
		return {"success": True, "download_count": pq_doc.download_count}
	except Exception as e:
		return {"success": False, "message": str(e)}
