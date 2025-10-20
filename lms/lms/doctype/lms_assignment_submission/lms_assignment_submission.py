# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import validate_url


class LMSAssignmentSubmission(Document):
	def validate(self):
		# self.validate_duplicates()
		self.validate_url()
		self.validate_status()

	# def validate_duplicates(self):
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

	def auto_grade_quiz(self):
		"""
		Go through quiz_questions from assignment, compare with answers in self.quiz_answers.
		Calculate percentage based on test_score and track attempts.
		"""
		try:
			assignment = frappe.get_doc("LMS Assignment", self.assignment)

			# Check if attempts are available
			attempts_allowed = assignment.get("attempts_allowed", 1)
			attempts_made = assignment.get("attempts_made", 0)

			if attempts_made >= attempts_allowed:
				frappe.throw(f"No attempts remaining for this assignment. ({attempts_made}/{attempts_allowed} used)")

			total_score = 0
			max_possible_score = 0

			# Get quiz questions
			quiz_questions = assignment.get("quiz_questions", [])

			if not quiz_questions:
				frappe.throw("No quiz questions found in this assignment.")

			# Create a dict of student answers for easy lookup
			student_answers = {ans.question: ans.selected_option for ans in self.quiz_answers}

			# Clear existing quiz_answers to avoid duplicates
			self.quiz_answers = []

			for q in quiz_questions:
				# Get marks for this question (default to 1 if not set)
				question_marks = q.get("marks", 1)
				max_possible_score += question_marks

				# Get student's selected option
				selected = student_answers.get(q.name, "")

				# Check if answer is correct
				correct_answer = q.get("correct_answer", "").strip()
				is_correct = selected.strip() == correct_answer if selected and correct_answer else False
				marks = question_marks if is_correct else 0
				total_score += marks

				# Append row
				self.append(
					"quiz_answers",
					{
						"question": q.name,
						"selected_option": selected,
						"is_correct": 1 if is_correct else 0,
						"marks_awarded": marks,
					}
				)

			# Get test_score from assignment (default to 100 if not set)
			test_score_value = float(assignment.get("test_score") or 100)

			# Calculate percentage based on marks obtained vs max possible
			if max_possible_score > 0:
				percentage = (total_score / max_possible_score) * 100
				# Scale to test_score
				final_score = (percentage / 100) * test_score_value
			else:
				percentage = 0
				final_score = 0

			# Set scores
			self.score = round(final_score, 2)
			self.total_score = int(test_score_value)

			# Set status based on percentage (50% pass threshold)
			self.status = "Pass" if percentage >= 50 else "Fail"

			# Set comments with detailed breakdown
			self.comments = f"""Auto graded: {total_score}/{max_possible_score} correct
Percentage: {percentage:.2f}%
Final Score: {final_score:.2f}/{test_score_value}"""

			# INCREMENT attempts_made instead of decrementing attempts_allowed
			new_attempts_made = attempts_made + 1
			frappe.db.set_value("LMS Assignment", self.assignment, "attempts_made", new_attempts_made)
			frappe.db.commit()

			self.save(ignore_permissions=True)

		except Exception as e:
			frappe.log_error(title="Auto Grade Quiz Error", message=frappe.get_traceback())
			raise

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
def grade_assignment(name, result, comments, score, totalScore, file):
	doc = frappe.get_doc("LMS Assignment Submission", name)
	doc.status = result
	doc.comments = comments
	doc.score = score
	doc.total_score = totalScore
	doc.file = file
	doc.save(ignore_permissions=True)
	return {"message": "Assignment graded successfully."}


@frappe.whitelist()
def submit_quiz(assignment, answers):
	"""
	answers = [{ "question": "QQ-230924-00001", "selected_option": "A" }, ...]
	"""
	try:
		if frappe.session.user == "Guest":
			frappe.throw(_("Login required"))

		# Parse answers if they come as JSON string
		if isinstance(answers, str):
			import json
			answers = json.loads(answers)

		assignment_doc = frappe.get_doc("LMS Assignment", assignment)

		if assignment_doc.type != "Quiz/Multiple choice":
			frappe.throw(_("Assignment is not a quiz."))

		# Get attempts tracking
		attempts_allowed = assignment_doc.get("attempts_allowed", 1)
		attempts_made = assignment_doc.get("attempts_made", 0)

		# Check if user has exceeded attempts
		if attempts_made >= attempts_allowed:
			frappe.throw(_(f"You have used all your attempts for this assignment. ({attempts_made}/{attempts_allowed} used)"))

		# Count existing submissions for this user
		submission_count = frappe.db.count(
			"LMS Assignment Submission",
			{"assignment": assignment, "member": frappe.session.user}
		)

		# Create submission doc
		submission = frappe.get_doc(
			{
				"doctype": "LMS Assignment Submission",
				"assignment": assignment,
				"member": frappe.session.user,
				"type": assignment_doc.type,
				"status": "Not Graded",
			}
		)

		# Add quiz answers to submission
		for ans in answers:
			submission.append(
				"quiz_answers",
				{
					"question": ans.get("question"),
					"selected_option": ans.get("selected_option", ""),
				}
			)

		submission.insert(ignore_permissions=True)

		# Now run auto-grading (this will increment attempts_made)
		submission.auto_grade_quiz()

		# Update Assignment status to Submitted (only on first submission)
		if submission_count == 0:
			frappe.db.set_value("LMS Assignment", assignment, {
				"status": "Submitted",
				"submitted": 1
			})

		frappe.db.commit()

		# Reload submission to get updated values
		submission.reload()

		# Get updated attempts from database
		updated_attempts_made = frappe.db.get_value("LMS Assignment", assignment, "attempts_made")
		attempts_remaining = attempts_allowed - updated_attempts_made

		# Prepare response with detailed answers
		detailed_answers = []
		for quiz_ans in submission.quiz_answers:
			detailed_answers.append(
				{
					"question": quiz_ans.question,
					"selected_option": quiz_ans.selected_option,
					"is_correct": quiz_ans.get("is_correct", 0),
					"marks_awarded": quiz_ans.get("marks_awarded", 0),
				}
			)

		return {
			"submission": submission.name,
			"score": submission.get("score", 0),
			"total_score": submission.get("total_score", 100),
			"percentage": round((submission.get("score", 0) / submission.get("total_score", 100) * 100), 2) if submission.get("total_score") else 0,
			"status": submission.status,
			"answers": detailed_answers,
			"attempts_made": updated_attempts_made,
			"attempts_allowed": attempts_allowed,
			"attempts_remaining": attempts_remaining if attempts_remaining > 0 else 0,
			"comments": submission.get("comments", "")
		}

	except Exception as e:
		frappe.log_error(title="Submit Quiz Error", message=frappe.get_traceback())
		frappe.throw(_(f"Error submitting quiz: {str(e)}"))

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


# get all the submissions for an assignment created by a tutor
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
