# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import validate_url


class LMSAssignmentSubmission(Document):
	def validate(self):
		self.validate_duplicates()
		self.validate_url()
		self.validate_status()

	def validate_duplicates(self):
		if frappe.db.exists(
			"LMS Assignment Submission",
			{"assignment": self.assignment, "member": self.member, "name": ["!=", self.name]},
		):
			lesson_title = frappe.db.get_value("Course Lesson", self.lesson, "title")
			frappe.throw(
				_("Assignment for Lesson {0} by {1} already exists.").format(lesson_title, self.member_name)
			)

	def validate_url(self):
		if self.type == "URL" and not validate_url(self.answer):
			frappe.throw(_("Please enter a valid URL."))

	def validate_status(self):
		if not self.is_new():
			doc_before_save = self.get_doc_before_save()
			if doc_before_save.status != self.status or doc_before_save.comments != self.comments:
				self.trigger_update_notification()

	def trigger_update_notification(self):
		notification = frappe._dict(
			{
				"subject": _("There has been an update on your submission for assignment {0}").format(
					self.assignment_title
				),
				"email_content": self.comments,
				"document_type": self.doctype,
				"document_name": self.name,
				"for_user": self.owner,
				"from_user": self.evaluator,
				"type": "Alert",
				"link": f"/assignment-submission/{self.assignment}/{self.name}",
			}
		)
		make_notification_logs(notification, [self.member])


@frappe.whitelist()
def upload_assignment(
	assignment_attachment=None,
	answer=None,
	assignment=None,
	lesson=None,
	status="Not Graded",
	comments=None,
	submission=None,
):
	if frappe.session.user == "Guest":
		return

	assignment_details = frappe.db.get_value(
		"LMS Assignment", assignment, ["type", "grade_assignment"], as_dict=1
	)
	assignment_type = assignment_details.type

	if assignment_type in ["Essay/Written task", "Practical task"] and not answer:
		frappe.throw(_("Please enter the URL for assignment submission."))

	if assignment_type == "Video submission" and not assignment_attachment:
		frappe.throw(_("Please upload the assignment file."))

	if assignment_type == "URL" and not validate_url(answer):
		frappe.throw(_("Please enter a valid URL."))

	if submission:
		doc = frappe.get_doc("LMS Assignment Submission", submission)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "LMS Assignment Submission",
				"assignment": assignment,
				"lesson": lesson,
				"member": frappe.session.user,
				"type": assignment_type,
			}
		)

	doc.update(
		{
			"assignment_attachment": assignment_attachment,
			"status": "Not Applicable"
			if assignment_type == "Text" and not assignment_details.grade_assignment
			else status,
			"comments": comments,
			"answer": answer,
		}
	)
	doc.save(ignore_permissions=True)
	return {
		"message": "Assignment submitted successfully.",
		"submission": doc.name,
	}


@frappe.whitelist()
def get_assignment(lesson):
	assignment = frappe.db.get_value(
		"LMS Assignment Submission",
		{"lesson": lesson, "member": frappe.session.user},
		["name", "lesson", "member", "assignment_attachment", "comments", "status"],
		as_dict=True,
	)
	assignment.file_name = frappe.db.get_value(
		"File", {"file_url": assignment.assignment_attachment}, "file_name"
	)
	return assignment


@frappe.whitelist()
def grade_assignment(name, result, comments, score, totalScore):
	doc = frappe.get_doc("LMS Assignment Submission", name)
	doc.status = result
	doc.comments = comments
	doc.score = score
	doc.total_score = totalScore
	doc.save(ignore_permissions=True)
	return {"message": "Assignment graded successfully."}


def after_insert(self):
	# Auto grade if assignment is quiz
	assignment_type = frappe.db.get_value("LMS Assignment", self.assignment, "type")
	if assignment_type == "Quiz/Multiple choice":
		self.auto_grade_quiz()


def auto_grade_quiz(self):
	"""
	Go through quiz_questions from assignment, compare with answers in self.quiz_answers.
	"""
	assignment = frappe.get_doc("LMS Assignment", self.assignment)
	total_score = 0

	for q in assignment.quiz_questions:
		# find student selected option
		selected = next((a.selected_option for a in self.quiz_answers if a.question == q.name), None)
		is_correct = selected and (selected.strip() == q.correct_answer)
		marks = q.marks if is_correct else 0
		total_score += marks

		# update / append row
		self.append(
			"quiz_answers",
			{
				"question": q.name,
				"selected_option": selected or "",
				"is_correct": is_correct,
				"marks_awarded": marks,
			},
		)

	# set status automatically if quiz
	self.status = "Pass" if total_score >= 0 else "Fail"  # adjust threshold
	self.db_set("comments", f"Auto graded: {total_score} points")
	self.save(ignore_permissions=True)


@frappe.whitelist()
def submit_quiz(assignment, answers):
	"""
	answers = [{ "question": "QQ-230924-00001", "selected_option": "A" }, ...]
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Login required"))

	assignment_doc = frappe.get_doc("LMS Assignment", assignment)
	if assignment_doc.type != "Quiz/Multiple choice":
		frappe.throw(_("Assignment is not a quiz."))

	# Prevent duplicate submission
	if frappe.db.exists(
		"LMS Assignment Submission", {"assignment": assignment, "member": frappe.session.user}
	):
		frappe.throw(_("You have already submitted this quiz."))

	total_score = 0
	detailed_answers = []

	for ans in answers:
		q = frappe.get_doc("LMS Quiz Question", ans["question"])
		selected = ans.get("selected_option")
		correct = q.correct_answer

		is_correct = selected == correct
		marks = q.marks if hasattr(q, "marks") else (1 if is_correct else 0)

		detailed_answers.append(
			{
				"question": q.name,
				"selected_option": selected,
				"correct_option": correct,
				"is_correct": is_correct,
				"marks_awarded": marks,
			}
		)

		total_score += marks

	# Create submission doc
	submission = frappe.get_doc(
		{
			"doctype": "LMS Assignment Submission",
			"assignment": assignment,
			"member": frappe.session.user,
			"type": assignment_doc.type,
			"status": "Pass" if total_score > 0 else "Fail",
			"comments": f"Auto-graded score: {total_score}",
			# store answers as JSON string
			"answer": frappe.as_json(detailed_answers),
		}
	)
	submission.insert(ignore_permissions=True)

	return {"submission": submission.name, "score": total_score, "answers": detailed_answers}


@frappe.whitelist()
def get_student_submitted_assignments(student):
	students_link = frappe.get_all(
		"PL Students",
		filters={"students": student},
		fields=["parent"],
	)
	assignment_ids = [s.parent for s in students_link]

	if not assignment_ids:
		return {"success": True, "data": []}

	submitted_assignments = frappe.get_all(
		"LMS Assignment Submission",
		filters={"assignment": ["in", assignment_ids], "member": student},
		fields=["*"],
		order_by="creation desc",
	)

	return {"success": True, "data": submitted_assignments}

#get all the submissions for an assignment created by a tutor
@frappe.whitelist()
def get_all_assignment_submissions(tutor):
	assignments = frappe.get_all(
		"LMS Assignment",
		filters={"owner": tutor},
		fields=["name", "title"],
	)

	if not assignments:
		return {"success": True, "data": []}

	assignment_ids = [a.name for a in assignments]

	submissions = frappe.get_all(
		"LMS Assignment Submission",
		filters={"assignment": ["in", assignment_ids]},
		fields=["*"],
		order_by="creation desc",
	)

	return {"success": True, "data": submissions}
