# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import datetime
import json
import random

import boto3
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, today
from private_learn_api.utils.reponse import paginated_response

from lms.lms.utils import get_chapters

from ...utils import generate_slug, update_payment_record, validate_image


class LMSCourse(Document):
	def validate(self):
		self.validate_published()
		self.validate_instructors()
		self.validate_video_link()
		self.validate_status()
		self.validate_payments_app()
		self.validate_certification()
		self.validate_amount_and_currency()
		self.image = validate_image(self.image)
		self.validate_card_gradient()

	def validate_published(self):
		if self.published and not self.published_on:
			self.published_on = today()

	def validate_instructors(self):
		if self.is_new() and not self.instructors:
			frappe.get_doc(
				{
					"doctype": "Course Instructor",
					"instructor": self.owner,
					"parent": self.name,
					"parentfield": "instructors",
					"parenttype": "LMS Course",
				}
			).save(ignore_permissions=True)

	def validate_video_link(self):
		if self.video_link and "/" in self.video_link:
			self.video_link = self.video_link.split("/")[-1]

	def validate_status(self):
		if self.published:
			self.status = "On going"

	def validate_payments_app(self):
		if self.paid_course:
			installed_apps = frappe.get_installed_apps()
			if "payments" not in installed_apps:
				documentation_link = "https://docs.frappe.io/learning/setting-up-payment-gateway"
				frappe.throw(
					_(
						"Please install the Payments App to create a paid course. Refer to the documentation for more details. {0}"
					).format(documentation_link)
				)

	def validate_certification(self):
		if self.enable_certification and self.paid_certificate:
			frappe.throw(_("A course cannot have both paid certificate and certificate of completion."))

		if self.paid_certificate and not self.evaluator:
			frappe.throw(_("Evaluator is required for paid certificates."))

	def validate_amount_and_currency(self):
		if self.paid_course and (cint(self.course_price) < 0 or not self.currency):
			frappe.throw(_("Amount and currency are required for paid courses."))

		if self.paid_certificate and (cint(self.course_price) <= 0 or not self.currency):
			frappe.throw(_("Amount and currency are required for paid certificates."))

	def validate_card_gradient(self):
		if not self.image and not self.card_gradient:
			colors = [
				"Red",
				"Blue",
				"Green",
				"Yellow",
				"Orange",
				"Pink",
				"Amber",
				"Violet",
				"Cyan",
				"Teal",
				"Gray",
				"Purple",
			]
			self.card_gradient = random.choice(colors)

	def on_update(self):
		if not self.upcoming and self.has_value_changed("upcoming"):
			self.send_email_to_interested_users()

	def on_payment_authorized(self, payment_status):
		if payment_status in ["Authorized", "Completed"]:
			update_payment_record("LMS Course", self.name)

	def send_email_to_interested_users(self):
		interested_users = frappe.get_all("LMS Course Interest", {"course": self.name}, ["name", "user"])
		subject = self.title + " is available!"
		args = {
			"title": self.title,
			"course_link": f"/lms/courses/{self.name}",
			"app_name": frappe.db.get_single_value("System Settings", "app_name"),
			"site_url": frappe.utils.get_url(),
		}

		for user in interested_users:
			args["first_name"] = frappe.db.get_value("User", user.user, "first_name")
			email_args = frappe._dict(
				recipients=user.user,
				subject=subject,
				header=[subject, "green"],
				template="lms_course_interest",
				args=args,
				now=True,
			)
			frappe.enqueue(method=frappe.sendmail, queue="short", timeout=300, is_async=True, **email_args)
			frappe.db.set_value("LMS Course Interest", user.name, "email_sent", True)

	def autoname(self):
		if not self.name:
			self.name = generate_slug(self.title, "LMS Course")

	def __repr__(self):
		return f"<Course#{self.name}>"

	def has_mentor(self, email):
		"""Checks if this course has a mentor with given email."""
		if not email or email == "Guest":
			return False

		mapping = frappe.get_all("LMS Course Mentor Mapping", {"course": self.name, "mentor": email})
		return mapping != []

	def add_mentor(self, email):
		"""Adds a new mentor to the course."""
		if not email:
			raise ValueError("Invalid email")
		if email == "Guest":
			raise ValueError("Guest user can not be added as a mentor")

		# given user is already a mentor
		if self.has_mentor(email):
			return

		doc = frappe.get_doc({"doctype": "LMS Course Mentor Mapping", "course": self.name, "mentor": email})
		doc.insert()

	def get_student_batch(self, email):
		"""Returns the batch the given student is part of.

		Returns None if the student is not part of any batch.
		"""
		if not email:
			return

		batch_name = frappe.get_value(
			doctype="LMS Enrollment",
			filters={"course": self.name, "member_type": "Student", "member": email},
			fieldname="batch_old",
		)
		return batch_name and frappe.get_doc("LMS Batch Old", batch_name)

	def get_batches(self, mentor=None):
		batches = frappe.get_all("LMS Batch Old", {"course": self.name})
		if mentor:
			# TODO: optimize this
			memberships = frappe.db.get_all("LMS Enrollment", {"member": mentor}, ["batch_old"])
			batch_names = {m.batch_old for m in memberships}
			return [b for b in batches if b.name in batch_names]

	def get_cohorts(self):
		return frappe.get_all(
			"Cohort",
			{"course": self.name},
			["name", "slug", "title", "begin_date", "end_date"],
			order_by="creation",
		)

	def get_cohort(self, cohort_slug):
		name = frappe.get_value("Cohort", {"course": self.name, "slug": cohort_slug})
		return name and frappe.get_doc("Cohort", name)

	def reindex_exercises(self):
		for i, c in enumerate(get_chapters(self.name), start=1):
			self._reindex_exercises_in_chapter(c, i)

	def _reindex_exercises_in_chapter(self, c, index):
		i = 1
		for lesson in self.get_lessons(c):
			for exercise in lesson.get_exercises():
				exercise.index_ = i
				exercise.index_label = f"{index}.{i}"
				exercise.save()
				i += 1

	def get_all_memberships(self, member):
		all_memberships = frappe.get_all(
			"LMS Enrollment", {"member": member, "course": self.name}, ["batch_old"]
		)
		for membership in all_memberships:
			membership.batch_title = frappe.db.get_value("LMS Batch Old", membership.batch_old, "title")
		return all_memberships


@frappe.whitelist()
def reindex_exercises(doc):
	course_data = json.loads(doc)
	course = frappe.get_doc("LMS Course", course_data["name"])
	course.reindex_exercises()
	frappe.msgprint("All exercises in this course have been re-indexed.")


@frappe.whitelist(allow_guest=True)
def get_all_instructors_course(tutor, published=None, is_draft=None, limit=None):
	"""Get all courses for a given instructor using serialize_course structure"""

	filters = {}
	if published is not None:
		filters["published"] = cint(published)
	if is_draft is not None:
		filters["draft"] = cint(is_draft)

	limit = int(limit) if limit else 100

	# Step 1: Get all course names linked to instructor
	course_names = frappe.get_all("Course Instructor", filters={"instructor": tutor}, pluck="parent")

	if not course_names:
		return {"success": True, "data": [], "count": 0}

	# Step 2: Get courses with additional filters
	course_filters = {"name": ["in", course_names]}
	course_filters.update(filters)
	courses = frappe.get_all(
		"LMS Course",
		filters=course_filters,
		fields=["name"],
		limit=limit,
		order_by="modified desc",
	)

	# Step 3: Serialize each course
	serialized_courses = [serialize_course(c["name"]) for c in courses]

	# Step 4: Add instructor profile data
	profile_data = {}
	if frappe.db.exists("User Profile", {"user": tutor}):
		profile_doc = frappe.get_doc("User Profile", {"user": tutor})
		profile_data = profile_doc.as_dict()

	for course in serialized_courses:
		course["instructor_profile"] = profile_data

	return {
		"success": True,
		"data": serialized_courses,
		"count": len(serialized_courses),
	}


@frappe.whitelist(allow_guest=True)
def get_all_courses(limit=None, **kwargs):
	limit = int(limit) if limit else 100
	filters = {}
	filters.update(kwargs)
	course_names = frappe.get_all(
		"LMS Course", fields=["name"], filters=filters, limit=limit, order_by="creation desc"
	)

	courses = [serialize_course(c["name"]) for c in course_names]

	return {"success": True, "data": courses, "count": len(courses)}


def serialize_course(course_name):
	"""Return a structured course with profile, chapters, and lessons"""
	course = frappe.get_doc("LMS Course", course_name)

	# Instructor(s)
	instructors = frappe.get_all("Course Instructor", filters={"parent": course.name}, fields=["instructor"])
	instructor_profiles = []
	for inst in instructors:
		profile_data = frappe.get_value("User Profile", {"user": inst["instructor"]}, "*", as_dict=True)
		if profile_data:
			user_doc = frappe.get_doc("User", profile_data["user"])
			instructor_profiles.append(
				{
					"id": profile_data.name,
					"full_name": user_doc.full_name,
					"email": user_doc.email,
					"phone_number": profile_data.phone_number,
					"profile_image_url": user_doc.user_image,
					"bio": profile_data.bio,
					"rating": profile_data.rating,
					"experience_years": profile_data.teaching_experience,
					"subjects": json.loads(profile_data.subjects) if profile_data.subjects else [],
				}
			)

	# Reviews
	reviews = frappe.get_all(
		"LMS Course Review", {"course": course.name}, ["name", "rating", "review", "owner", "creation"]
	)
	reviews_list = []
	reviewer_name = frappe.get_all(
		"User",
		filters={"name": reviews[0].owner} if reviews else {},
		fields=["full_name", "user_image"],
	)
	reviewer = reviewer_name[0]["full_name"] if reviewer_name else ""
	for r in reviews:
		reviews_list.append(
			{
				"id": r.name,
				"reviewer_name": reviewer,
				"rating": r.rating,
				"comment": r.review,
				"date": r.creation,
			}
		)

	# Subject
	subject = None
	if course.subject:
		subject_name = frappe.get_value("Subject", course.subject, "subject_name")
		if subject_name:
			subject_doc = frappe.get_doc("Subject", course.subject)
			subject = {"name": subject_doc.name, "subject_name": subject_doc.subject_name}

	# Educational Level
	education_level = None
	if getattr(course, "course_level", None):
		education_level_name = frappe.get_value("LMS Course Level", course.course_level, "education_level")
		if education_level_name:
			education_level_doc = frappe.get_doc("LMS Course Level", course.course_level)
			education_level = {
				"name": education_level_doc.name,
				"level_name": education_level_doc.education_level,
			}
	# Chapters & Lessons - Fixed to only query existing fields
	chapters_list = []

	# First, get the actual fields available in Course Chapter
	try:
		# Try with common fields that should exist
		chapters = frappe.get_all(
			"Course Chapter", filters={"course": course.name}, fields=["name", "title", "idx"], order_by="idx"
		)
	except Exception as e:
		# Fallback if even basic fields don't exist
		frappe.log_error(f"Course Chapter query failed: {str(e)}", "serialize_course")
		chapters = []

	for chapter in chapters:
		try:
			lessons = frappe.get_all(
				"Course Lesson",
				filters={"chapter": chapter.name},
				fields=[
					"name",
					"title",
					"content_type",
					"content_order",
					"is_published",
					"essay_title",
					"essay_content",
					"video_title",
					"video_url",
					"video_description",
					"video_content",
					"quiz_title",
					"quiz_description",
					"body",
					"content",
					"youtube",
					"quiz_id",
				],
				order_by="content_order, idx",
			)
		except Exception as e:
			# Fallback for Course Lesson fields that might not exist
			frappe.log_error(f"Course Lesson query failed: {str(e)}", "serialize_course")
			try:
				# Try with minimal fields
				lessons = frappe.get_all(
					"Course Lesson",
					filters={"chapter": chapter.name},
					fields=["name", "title"],
					order_by="idx",
				)
			except:
				lessons = []

		lessons_list = []
		for lesson in lessons:
			quiz_questions = []
			if lesson.get("content_type") == "Quiz":
				try:
					quiz_questions = frappe.get_all(
						"LMS Quiz Question",
						filters={"parent": lesson["name"], "parenttype": "Course Lesson"},
						fields=[
							"name",
							"question",
							"question_type",
							"option_a",
							"option_b",
							"option_c",
							"option_d",
							"correct_answer",
							"marks",
						],
					)
				except Exception as e:
					frappe.log_error(f"Quiz Questions query failed: {str(e)}", "serialize_course")
					quiz_questions = []

			lesson_data = {
				"id": lesson.get("name"),
				"title": lesson.get("title"),
				"content_type": lesson.get("content_type", "Lesson"),
				"content_order": lesson.get("content_order", 1),
				"is_published": lesson.get("is_published", 1),
			}

			# Add content based on type
			if lesson.get("content_type") == "Essay":
				lesson_data["essay"] = {
					"title": lesson.get("essay_title"),
					"content": lesson.get("essay_content"),
				}
			elif lesson.get("content_type") == "Video":
				lesson_data["video"] = {
					"title": lesson.get("video_title"),
					"description": lesson.get("video_description"),
					"url": lesson.get("video_content") or lesson.get("video_url"),
					"youtube_url": lesson.get("youtube"),
				}
			elif lesson.get("content_type") == "Quiz":
				lesson_data["quiz"] = {
					"title": lesson.get("quiz_title"),
					"description": lesson.get("quiz_description"),
					"questions": quiz_questions,
					"quiz_id": lesson.get("quiz_id"),
				}
			else:  # Default Lesson type
				lesson_data["lesson"] = {
					"body": lesson.get("body"),
					"content": lesson.get("content"),
					"youtube_url": lesson.get("youtube"),
					"quiz_id": lesson.get("quiz_id"),
				}

			lessons_list.append(lesson_data)

		chapters_list.append(
			{
				"id": chapter.name,
				"title": chapter.title,
				"description": "",  # Set empty string since description field doesn't exist
				"idx": chapter.idx,
				"lessons": lessons_list,
			}
		)

	# Final Structured Response
	return {
		"id": course.name,
		"title": course.title,
		"tags": course.tags,
		"status": course.status,
		"image": course.image,
		"published": course.published,
		"published_on": course.published_on,
		"featured": course.featured,
		"short_introduction": course.short_introduction,
		"description": course.description,
		"requirement": course.requirement,
		"course_language": course.course_language,
		"education_level": education_level,
		"subject": subject,
		"price": course.course_price,
		"currency": course.currency,
		"rating": course.rating,
		"enrollments": course.enrollments,
		"instructors": instructor_profiles,
		"reviews": reviews_list,
		"chapters": chapters_list,
		"introductory_video": course.video,
		"Doctype": "LMS Course",
	}


@frappe.whitelist(allow_guest=True)
def get_course_detail_old(course_name):
	"""
	Fetch a single course by name with full details.
	Uses serialize_course() so output is identical to list.
	"""
	if not course_name:
		frappe.throw("Course name is required")

	course_data = serialize_course(course_name)

	return {"success": True, "data": course_data}


@frappe.whitelist()
def create_course():
	"""
	Create a comprehensive course with chapters, lessons, and settings.
	Creates both standalone Course Chapter/Lesson docs AND child table references.
	Properly handles LMS Question → LMS Quiz Question relationship with proper naming.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# === Prepare all data first ===
		chapters_data = []
		lessons_created = []
		quiz_questions_created = []

		if "modules" in data:
			for chapter_idx, module_data in enumerate(data["modules"]):
				chapter_data = {"title": module_data.get("title", ""), "lessons": []}

				if "contentBlocks" in module_data:
					for block_idx, content_block in enumerate(module_data["contentBlocks"]):
						content_type = content_block.get("type", "Lesson")
						content_data = content_block.get("data", {})

						lesson_data = {
							"title": content_block.get("title", ""),
							"content_type": content_type.title(),
							"content_order": block_idx + 1,
							"content_data": content_data,
						}
						chapter_data["lessons"].append(lesson_data)

				chapters_data.append(chapter_data)

		# === Create Course with all chapter references at once ===
		course_doc = frappe.new_doc("LMS Course")
		course_doc.title = data.get("title", "")
		course_doc.description = data.get("courseDescription", "")
		course_doc.short_introduction = data.get("courseDescription", "")[:500]
		course_doc.image = data.get("thumbnailImage", "")
		course_doc.video = data.get("introductoryVideo", "")
		course_doc.tags = (
			",".join(data.get("tags", []))
			if isinstance(data.get("tags"), list)
			else data.get("tagCategory", "")
		)
		course_doc.category = data.get("category", "")
		course_doc.education_level = data.get("educationLevel", "")
		course_doc.course_language = data.get("courseLanguage", "")
		course_doc.paid_course = 1 if data.get("pricingModel") == "paid" else 0
		course_doc.course_price = data.get("price", 0) if data.get("pricingModel") == "paid" else 0
		course_doc.currency = "USD" if data.get("pricingModel") == "paid" else ""
		course_doc.requirement = data.get("requirements", "")
		course_doc.objectives = data.get("courseObjective", "")
		course_doc.published = 1 if data.get("visibility") == "public" else 0
		course_doc.draft = 0 if data.get("visibility") == "public" else 1
		course_doc.enable_certification = 1 if data.get("issueCertificate", False) else 0

		# Add instructor
		course_doc.append("instructors", {"instructor": frappe.session.user}) # or data.get("instructor", frappe.session.user)

		# Insert course first to get the name
		course_doc.insert(ignore_permissions=True)

		# === Now create chapters and lessons ===
		chapters_created = []

		for chapter_idx, chapter_info in enumerate(chapters_data):
			# Create Course Chapter
			chapter_doc = frappe.new_doc("Course Chapter")
			chapter_doc.course = course_doc.name
			chapter_doc.title = chapter_info["title"]
			chapter_doc.insert(ignore_permissions=True)

			chapters_created.append(
				{
					"name": chapter_doc.name,
					"title": chapter_doc.title,
				}
			)

			# Create lessons for this chapter
			for lesson_info in chapter_info["lessons"]:
				# Create Course Lesson
				lesson_doc = frappe.new_doc("Course Lesson")
				lesson_doc.chapter = chapter_doc.name
				lesson_doc.course = course_doc.name
				lesson_doc.title = lesson_info["title"]
				lesson_doc.content_type = lesson_info["content_type"]
				lesson_doc.content_order = lesson_info["content_order"]
				lesson_doc.is_published = 1

				content_data = lesson_info["content_data"]
				content_type = lesson_info["content_type"].lower()

				# Set content based on type
				if content_type == "essay":
					lesson_doc.essay_title = lesson_info["title"]
					lesson_doc.essay_content = content_data.get("content", "")
				elif content_type == "video":
					lesson_doc.video_title = lesson_info["title"]
					lesson_doc.video_url = content_data.get("videoUrl", "")
					lesson_doc.video_description = content_data.get("description", "")
				elif content_type == "quiz":
					lesson_doc.quiz_title = lesson_info["title"]
					lesson_doc.quiz_description = content_data.get("description", "")

				lesson_doc.insert(ignore_permissions=True)

				# Add lesson reference to chapter
				chapter_doc.append("lessons", {"lesson": lesson_doc.name})

				lessons_created.append(
					{
						"name": lesson_doc.name,
						"type": content_type,
						"title": lesson_doc.title,
						"chapter": chapter_doc.name,
					}
				)

				# Create quiz questions if this is a quiz lesson
				if content_type == "quiz" and "questions" in content_data:
					for q_idx, question_data in enumerate(content_data["questions"]):
						# Create LMS Question
						lms_question_doc = frappe.new_doc("LMS Question")
						lms_question_doc.question = question_data.get("question", "")
						lms_question_doc.type = "Choices"
						lms_question_doc.multiple = 0

						# Handle options
						options = question_data.get("options", [])
						if len(options) > 0:
							lms_question_doc.option_1 = options[0]
						if len(options) > 1:
							lms_question_doc.option_2 = options[1]
						if len(options) > 2:
							lms_question_doc.option_3 = options[2]
						if len(options) > 3:
							lms_question_doc.option_4 = options[3]

						# Set correct answer
						correct_answer_index = question_data.get("correctAnswer", 0)
						lms_question_doc.is_correct_1 = 1 if correct_answer_index == 0 else 0
						lms_question_doc.is_correct_2 = 1 if correct_answer_index == 1 else 0
						lms_question_doc.is_correct_3 = 1 if correct_answer_index == 2 else 0
						lms_question_doc.is_correct_4 = 1 if correct_answer_index == 3 else 0

						lms_question_doc.insert(ignore_permissions=True)

						# Create LMS Quiz Question
						quiz_question_doc = frappe.new_doc("LMS Quiz Question")
						quiz_question_doc.question = lms_question_doc.name
						quiz_question_doc.marks = int(question_data.get("mark", 1))
						quiz_question_doc.question_type = "Multiple Choice"
						quiz_question_doc.points = int(question_data.get("mark", 1))
						quiz_question_doc.is_required = 0

						# Convert correct answer to letter
						correct_answer_letter = (
							["A", "B", "C", "D"][correct_answer_index] if correct_answer_index < 4 else "A"
						)
						quiz_question_doc.correct_answer = correct_answer_letter

						# Set options for compatibility
						quiz_question_doc.option_a = options[0] if len(options) > 0 else ""
						quiz_question_doc.option_b = options[1] if len(options) > 1 else ""
						quiz_question_doc.option_c = options[2] if len(options) > 2 else ""
						quiz_question_doc.option_d = options[3] if len(options) > 3 else ""
						quiz_question_doc.explanation = question_data.get("explanation", "")

						# Set parent relationship
						quiz_question_doc.parent = lesson_doc.name
						quiz_question_doc.parenttype = "Course Lesson"
						quiz_question_doc.parentfield = "quiz_questions"
						quiz_question_doc.idx = q_idx + 1

						quiz_question_doc.insert(ignore_permissions=True)

						quiz_questions_created.append(
							{
								"lms_question_name": lms_question_doc.name,
								"quiz_question_name": quiz_question_doc.name,
								"question": question_data.get("question", ""),
								"lesson": lesson_doc.name,
								"chapter": chapter_doc.name,
							}
						)

			# Save chapter with all its lessons
			chapter_doc.save(ignore_permissions=True)

		# === Create separate course update for chapter references ===
		# Get fresh copy of course to avoid timestamp issues
		course_update = frappe.get_doc("LMS Course", course_doc.name)

		# Add all chapter references
		for chapter in chapters_created:
			course_update.append("chapters", {"chapter": chapter["name"]})

		# Save course with chapter references
		course_update.save(ignore_permissions=True)

		# Commit all changes
		frappe.db.commit()

		return {
			"success": True,
			"message": "Course created successfully with chapters and lessons using proper Frappe naming and child table references",
			"data": {
				"course_name": course_doc.name,
				"course_title": course_doc.title,
				"pricing_model": data.get("pricingModel", "free"),
				"price": data.get("price", 0),
				"chapters_count": len(chapters_created),
				"lessons_count": len(lessons_created),
				"quiz_questions_count": len(quiz_questions_created),
				"chapters": chapters_created,
				"lessons": lessons_created,
				"quiz_questions_details": quiz_questions_created,
			},
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Course Creation Failed")
		return {"error": str(e), "traceback": frappe.get_traceback()}

@frappe.whitelist(allow_guest=False, methods=["POST", "PUT", "PATCH"])
def update_course():
	"""
	Update an existing course with chapters, lessons, and settings.
	Handles updating, creating new, and deleting removed chapters/lessons/questions.
	Maintains proper parent-child relationships and naming conventions.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		course_name = data.get("course_name")
		if not course_name:
			return {"error": "course_name is required for update"}

		# Check if course exists
		if not frappe.db.exists("LMS Course", course_name):
			return {"error": f"Course {course_name} not found"}

		# Get existing course with ignore_permissions
		course_doc = frappe.get_doc("LMS Course", course_name)
		# Set ignore_permissions flag
		course_doc.flags.ignore_permissions = True

		# === Update course fields ===
		if "title" in data:
			new_title = data.get("title", "").strip()
			if new_title:
				course_doc.title = new_title
			elif not course_doc.title:
				return {"error": "Course title cannot be empty"}
		
		course_doc.description = data.get("courseDescription", course_doc.description)
		course_doc.short_introduction = data.get("courseDescription", course_doc.short_introduction)[:500]
		course_doc.image = data.get("thumbnailImage", course_doc.image)
		course_doc.video = data.get("introductoryVideo", course_doc.video)
		course_doc.tags = (
			",".join(data.get("tags", []))
			if isinstance(data.get("tags"), list)
			else data.get("tagCategory", course_doc.tags)
		)
		course_doc.category = data.get("category", course_doc.category)
		course_doc.education_level = data.get("educationLevel", course_doc.education_level)
		course_doc.course_language = data.get("courseLanguage", course_doc.course_language)
		course_doc.paid_course = 1 if data.get("pricingModel") == "paid" else 0
		course_doc.course_price = data.get("price", 0) if data.get("pricingModel") == "paid" else 0
		course_doc.currency = "USD" if data.get("pricingModel") == "paid" else course_doc.currency
		course_doc.requirement = data.get("requirements", course_doc.requirement)
		course_doc.objectives = data.get("courseObjective", course_doc.objectives)
		course_doc.published = 1 if data.get("visibility") == "public" else 0
		course_doc.draft = 0 if data.get("visibility") == "public" else 1
		course_doc.enable_certification = 1 if data.get("issueCertificate", False) else 0

		# Update instructor
		if data.get("instructor"):
			course_doc.instructors = []
			course_doc.append("instructors", {"instructor": data.get("instructor")})

		# Save course basic info first
		course_doc.save(ignore_permissions=True)

		# === Track existing and new data ===
		existing_chapters = {
			ch.name: ch for ch in frappe.get_all(
				"Course Chapter",
				filters={"course": course_name},
				fields=["name", "title"],
				ignore_permissions=True
			)
		}
		
		chapters_to_keep = set()
		chapters_data = []
		lessons_created = []
		lessons_updated = []
		quiz_questions_created = []
		quiz_questions_updated = []

		# === Process incoming chapter data ===
		if "modules" in data:
			for chapter_idx, module_data in enumerate(data["modules"]):
				chapter_name = module_data.get("chapter_name")  # Optional: to update existing
				chapter_title = module_data.get("title", "").strip()
				
				# Validate chapter title
				if not chapter_title:
					return {
						"error": f"Title is required for chapter at position {chapter_idx + 1}",
						"chapter_index": chapter_idx
					}
				
				# Determine if updating or creating
				chapter_doc = None
				if chapter_name and frappe.db.exists("Course Chapter", chapter_name):
					# Update existing chapter
					chapter_doc = frappe.get_doc("Course Chapter", chapter_name)
					chapter_doc.flags.ignore_permissions = True
					chapter_doc.title = chapter_title
					chapter_doc.save(ignore_permissions=True)
					chapters_to_keep.add(chapter_name)
				else:
					# Create new chapter
					chapter_doc = frappe.new_doc("Course Chapter")
					chapter_doc.course = course_name
					chapter_doc.title = chapter_title
					chapter_doc.insert(ignore_permissions=True)
					chapters_to_keep.add(chapter_doc.name)

				chapter_info = {
					"name": chapter_doc.name,
					"title": chapter_doc.title,
					"lessons": []
				}

				# Get existing lessons for this chapter
				existing_lessons = {
					lesson.name: lesson for lesson in frappe.get_all(
						"Course Lesson",
						filters={"chapter": chapter_doc.name},
						fields=["name", "title", "content_type"],
						ignore_permissions=True
					)
				}
				
				lessons_to_keep = set()

				# Process content blocks (lessons)
				if "contentBlocks" in module_data:
					for block_idx, content_block in enumerate(module_data["contentBlocks"]):
						lesson_name = content_block.get("lesson_name")  # Optional: to update existing
						content_type = content_block.get("type", "Lesson").title()
						content_data = content_block.get("data", {})
						
						# Get title from data object or top level
						lesson_title = content_data.get("title", content_block.get("title", "")).strip()
						
						# Validate title
						if not lesson_title:
							return {
								"error": f"Title is required for content block at position {block_idx + 1} in chapter '{chapter_title}'",
								"chapter": chapter_title,
								"block_index": block_idx
							}

						lesson_doc = None
						is_new_lesson = False

						if lesson_name and frappe.db.exists("Course Lesson", lesson_name):
							# Update existing lesson
							lesson_doc = frappe.get_doc("Course Lesson", lesson_name)
							lesson_doc.flags.ignore_permissions = True
							lesson_doc.title = lesson_title
							lesson_doc.content_type = content_type
							lesson_doc.content_order = block_idx + 1
							lessons_to_keep.add(lesson_name)
						else:
							# Create new lesson
							lesson_doc = frappe.new_doc("Course Lesson")
							lesson_doc.chapter = chapter_doc.name
							lesson_doc.course = course_name
							lesson_doc.title = lesson_title
							lesson_doc.content_type = content_type
							lesson_doc.content_order = block_idx + 1
							lesson_doc.is_published = 1
							is_new_lesson = True

						# Update content based on type
						content_type_lower = content_type.lower()
						
						if content_type_lower == "essay":
							lesson_doc.essay_title = lesson_title
							lesson_doc.essay_content = content_data.get("content", "")
						elif content_type_lower == "video":
							lesson_doc.video_title = lesson_title
							lesson_doc.video_url = content_data.get("videoUrl", "")
							lesson_doc.video_description = content_data.get("description", "")
						elif content_type_lower == "quiz":
							lesson_doc.quiz_title = lesson_title
							lesson_doc.quiz_description = content_data.get("description", "")

						if is_new_lesson:
							lesson_doc.insert(ignore_permissions=True)
							lessons_to_keep.add(lesson_doc.name)
							lessons_created.append({
								"name": lesson_doc.name,
								"type": content_type_lower,
								"title": lesson_doc.title,
								"chapter": chapter_doc.name
							})
						else:
							lesson_doc.save(ignore_permissions=True)
							lessons_updated.append({
								"name": lesson_doc.name,
								"type": content_type_lower,
								"title": lesson_doc.title,
								"chapter": chapter_doc.name
							})

						# Handle quiz questions
						if content_type_lower == "quiz" and "questions" in content_data:
							# Get existing quiz questions for this lesson
							existing_quiz_questions = frappe.get_all(
								"LMS Quiz Question",
								filters={
									"parent": lesson_doc.name,
									"parenttype": "Course Lesson"
								},
								fields=["name", "question"],
								ignore_permissions=True
							)
							
							existing_quiz_q_dict = {q.name: q for q in existing_quiz_questions}
							quiz_questions_to_keep = set()

							for q_idx, question_data in enumerate(content_data["questions"]):
								quiz_question_name = question_data.get("quiz_question_name")
								
								# Check if updating or creating
								if quiz_question_name and frappe.db.exists("LMS Quiz Question", quiz_question_name):
									# Update existing quiz question and its LMS Question
									quiz_question_doc = frappe.get_doc("LMS Quiz Question", quiz_question_name)
									quiz_question_doc.flags.ignore_permissions = True
									lms_question_doc = frappe.get_doc("LMS Question", quiz_question_doc.question)
									lms_question_doc.flags.ignore_permissions = True
									
									# Handle both 'options' and 'answers' formats
									options = question_data.get("options") or question_data.get("answers", [])
									
									# Handle correctAnswer as letter (A, B, C, D) or index (0, 1, 2, 3)
									correct_answer = question_data.get("correctAnswer", 0)
									if isinstance(correct_answer, str):
										# Convert letter to index: A->0, B->1, C->2, D->3
										letter_to_index = {"A": 0, "B": 1, "C": 2, "D": 3}
										correct_answer_index = letter_to_index.get(correct_answer.upper(), 0)
									else:
										correct_answer_index = int(correct_answer)
									
									# Update LMS Question
									lms_question_doc.question = question_data.get("question", "")
									if len(options) > 0:
										lms_question_doc.option_1 = options[0]
									if len(options) > 1:
										lms_question_doc.option_2 = options[1]
									if len(options) > 2:
										lms_question_doc.option_3 = options[2]
									if len(options) > 3:
										lms_question_doc.option_4 = options[3]

									lms_question_doc.is_correct_1 = 1 if correct_answer_index == 0 else 0
									lms_question_doc.is_correct_2 = 1 if correct_answer_index == 1 else 0
									lms_question_doc.is_correct_3 = 1 if correct_answer_index == 2 else 0
									lms_question_doc.is_correct_4 = 1 if correct_answer_index == 3 else 0
									lms_question_doc.save(ignore_permissions=True)

									# Update Quiz Question
									quiz_question_doc.marks = int(question_data.get("mark") or question_data.get("marks", 1))
									quiz_question_doc.points = int(question_data.get("mark") or question_data.get("marks", 1))
									correct_answer_letter = (
										["A", "B", "C", "D"][correct_answer_index] if correct_answer_index < 4 else "A"
									)
									quiz_question_doc.correct_answer = correct_answer_letter
									quiz_question_doc.option_a = options[0] if len(options) > 0 else ""
									quiz_question_doc.option_b = options[1] if len(options) > 1 else ""
									quiz_question_doc.option_c = options[2] if len(options) > 2 else ""
									quiz_question_doc.option_d = options[3] if len(options) > 3 else ""
									quiz_question_doc.explanation = question_data.get("explanation", "")
									quiz_question_doc.idx = q_idx + 1
									quiz_question_doc.save(ignore_permissions=True)
									
									quiz_questions_to_keep.add(quiz_question_name)
									quiz_questions_updated.append({
										"lms_question_name": lms_question_doc.name,
										"quiz_question_name": quiz_question_doc.name,
										"question": question_data.get("question", ""),
										"lesson": lesson_doc.name
									})
								else:
									# Create new quiz question
									lms_question_doc = frappe.new_doc("LMS Question")
									lms_question_doc.question = question_data.get("question", "")
									lms_question_doc.type = "Choices"
									lms_question_doc.multiple = 0

									if len(options) > 0:
										lms_question_doc.option_1 = options[0]
									if len(options) > 1:
										lms_question_doc.option_2 = options[1]
									if len(options) > 2:
										lms_question_doc.option_3 = options[2]
									if len(options) > 3:
										lms_question_doc.option_4 = options[3]

									lms_question_doc.is_correct_1 = 1 if correct_answer_index == 0 else 0
									lms_question_doc.is_correct_2 = 1 if correct_answer_index == 1 else 0
									lms_question_doc.is_correct_3 = 1 if correct_answer_index == 2 else 0
									lms_question_doc.is_correct_4 = 1 if correct_answer_index == 3 else 0
									lms_question_doc.insert(ignore_permissions=True)

									quiz_question_doc = frappe.new_doc("LMS Quiz Question")
									quiz_question_doc.question = lms_question_doc.name
									quiz_question_doc.marks = int(question_data.get("mark") or question_data.get("marks", 1))
									quiz_question_doc.question_type = "Multiple Choice"
									quiz_question_doc.points = int(question_data.get("mark") or question_data.get("marks", 1))
									quiz_question_doc.is_required = 0

									correct_answer_letter = (
										["A", "B", "C", "D"][correct_answer_index] if correct_answer_index < 4 else "A"
									)
									quiz_question_doc.correct_answer = correct_answer_letter
									quiz_question_doc.option_a = options[0] if len(options) > 0 else ""
									quiz_question_doc.option_b = options[1] if len(options) > 1 else ""
									quiz_question_doc.option_c = options[2] if len(options) > 2 else ""
									quiz_question_doc.option_d = options[3] if len(options) > 3 else ""
									quiz_question_doc.explanation = question_data.get("explanation", "")
									quiz_question_doc.parent = lesson_doc.name
									quiz_question_doc.parenttype = "Course Lesson"
									quiz_question_doc.parentfield = "quiz_questions"
									quiz_question_doc.idx = q_idx + 1
									quiz_question_doc.insert(ignore_permissions=True)

									quiz_questions_to_keep.add(quiz_question_doc.name)
									quiz_questions_created.append({
										"lms_question_name": lms_question_doc.name,
										"quiz_question_name": quiz_question_doc.name,
										"question": question_data.get("question", ""),
										"lesson": lesson_doc.name
									})

							# Delete removed quiz questions
							for existing_q_name in existing_quiz_q_dict:
								if existing_q_name not in quiz_questions_to_keep:
									quiz_q_doc = frappe.get_doc("LMS Quiz Question", existing_q_name)
									quiz_q_doc.flags.ignore_permissions = True
									lms_q_name = quiz_q_doc.question
									frappe.delete_doc("LMS Quiz Question", existing_q_name, ignore_permissions=True)
									if frappe.db.exists("LMS Question", lms_q_name):
										frappe.delete_doc("LMS Question", lms_q_name, ignore_permissions=True)

						chapter_info["lessons"].append({
							"name": lesson_doc.name,
							"title": lesson_doc.title
						})

				# Delete removed lessons from this chapter
				for existing_lesson_name in existing_lessons:
					if existing_lesson_name not in lessons_to_keep:
						# Delete quiz questions first if it's a quiz lesson
						quiz_questions = frappe.get_all(
							"LMS Quiz Question",
							filters={"parent": existing_lesson_name, "parenttype": "Course Lesson"},
							fields=["name", "question"],
							ignore_permissions=True
						)
						for qq in quiz_questions:
							frappe.delete_doc("LMS Quiz Question", qq.name, ignore_permissions=True)
							if frappe.db.exists("LMS Question", qq.question):
								frappe.delete_doc("LMS Question", qq.question, ignore_permissions=True)
						
						# Delete the lesson
						frappe.delete_doc("Course Lesson", existing_lesson_name, ignore_permissions=True)

				# Update chapter's lesson child table
				chapter_doc = frappe.get_doc("Course Chapter", chapter_doc.name)
				chapter_doc.flags.ignore_permissions = True
				chapter_doc.lessons = []
				for lesson_info in chapter_info["lessons"]:
					chapter_doc.append("lessons", {"lesson": lesson_info["name"]})
				chapter_doc.save(ignore_permissions=True)

				chapters_data.append(chapter_info)

		# Delete removed chapters
		for existing_chapter_name in existing_chapters:
			if existing_chapter_name not in chapters_to_keep:
				# Delete all lessons in this chapter
				lessons = frappe.get_all(
					"Course Lesson",
					filters={"chapter": existing_chapter_name},
					fields=["name"],
					ignore_permissions=True
				)
				for lesson in lessons:
					# Delete quiz questions first
					quiz_questions = frappe.get_all(
						"LMS Quiz Question",
						filters={"parent": lesson.name, "parenttype": "Course Lesson"},
						fields=["name", "question"],
						ignore_permissions=True
					)
					for qq in quiz_questions:
						frappe.delete_doc("LMS Quiz Question", qq.name, ignore_permissions=True)
						if frappe.db.exists("LMS Question", qq.question):
							frappe.delete_doc("LMS Question", qq.question, ignore_permissions=True)
					
					frappe.delete_doc("Course Lesson", lesson.name, ignore_permissions=True)
				
				# Delete the chapter
				frappe.delete_doc("Course Chapter", existing_chapter_name, ignore_permissions=True)

		# Update course's chapter child table
		course_update = frappe.get_doc("LMS Course", course_name)
		course_update.flags.ignore_permissions = True
		course_update.chapters = []
		for chapter_info in chapters_data:
			course_update.append("chapters", {"chapter": chapter_info["name"]})
		course_update.save(ignore_permissions=True)

		# Commit all changes
		frappe.db.commit()

		return {
			"success": True,
			"message": "Course updated successfully",
			"data": {
				"course_name": course_name,
				"course_title": course_update.title,
				"chapters_count": len(chapters_data),
				"lessons_created": len(lessons_created),
				"lessons_updated": len(lessons_updated),
				"quiz_questions_created": len(quiz_questions_created),
				"quiz_questions_updated": len(quiz_questions_updated),
				"chapters": chapters_data,
				"new_lessons": lessons_created,
				"updated_lessons": lessons_updated,
				"new_quiz_questions": quiz_questions_created,
				"updated_quiz_questions": quiz_questions_updated
			}
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Course Update Failed")
		return {"error": str(e), "traceback": frappe.get_traceback()}

@frappe.whitelist()
def create_course_final():
	"""
	Create a comprehensive course with chapters, lessons, and settings.
	Uses Course Chapter and Course Lesson doctypes with Frappe API.
	Properly handles LMS Question → LMS Quiz Question relationship with proper naming.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# === Create Course using Frappe API ===
		course_doc = frappe.new_doc("LMS Course")
		course_doc.title = data.get("title", "")
		course_doc.description = data.get("courseDescription", "")
		course_doc.short_introduction = data.get("courseDescription", "")[:500]
		course_doc.image = data.get("thumbnailImage", "")
		course_doc.video = data.get("introductoryVideo", "")
		course_doc.tags = (
			",".join(data.get("tags", []))
			if isinstance(data.get("tags"), list)
			else data.get("tagCategory", "")
		)
		course_doc.category = data.get("category", "")
		course_doc.education_level = data.get("educationLevel", "")
		course_doc.course_language = data.get("courseLanguage", "")
		course_doc.paid_course = 1 if data.get("pricingModel") == "paid" else 0
		course_doc.course_price = data.get("price", 0) if data.get("pricingModel") == "paid" else 0
		course_doc.currency = "USD" if data.get("pricingModel") == "paid" else ""
		course_doc.requirement = data.get("requirements", "")
		course_doc.objectives = data.get("courseObjective", "")
		course_doc.published = 1 if data.get("visibility") == "public" else 0
		course_doc.draft = 0 if data.get("visibility") == "public" else 1
		course_doc.enable_certification = 1 if data.get("issueCertificate", False) else 0

		# Add instructor
		course_doc.append("instructors", {"instructor": data.get("instructor", frappe.session.user)})

		# Insert course first to get proper naming
		course_doc.insert(ignore_permissions=True)

		# === Create Chapters and Lessons ===
		chapters_created = []
		lessons_created = []
		quiz_questions_created = []

		if "modules" in data:
			for chapter_idx, module_data in enumerate(data["modules"]):
				# Create Course Chapter using Frappe API
				chapter_doc = frappe.new_doc("Course Chapter")
				chapter_doc.course = course_doc.name
				chapter_doc.title = module_data.get("title", "")
				chapter_doc.description = module_data.get("description", "")
				chapter_doc.idx = chapter_idx + 1
				chapter_doc.insert(ignore_permissions=True)

				chapters_created.append(
					{
						"name": chapter_doc.name,
						"title": chapter_doc.title,
						"description": chapter_doc.description,
					}
				)

				# === Create Course Lessons ===
				if "contentBlocks" in module_data:
					for block_idx, content_block in enumerate(module_data["contentBlocks"]):
						content_type = content_block.get("type", "Lesson")
						content_data = content_block.get("data", {})

						# Create Course Lesson using Frappe API
						lesson_doc = frappe.new_doc("Course Lesson")
						lesson_doc.chapter = chapter_doc.name
						lesson_doc.course = course_doc.name
						lesson_doc.title = content_block.get("title", "")
						lesson_doc.content_type = content_type.title()
						lesson_doc.content_order = block_idx + 1
						lesson_doc.is_published = 1

						# Set content based on type
						if content_type == "essay":
							lesson_doc.essay_title = content_block.get("title", "")
							lesson_doc.essay_content = content_data.get("content", "")
						elif content_type == "video":
							lesson_doc.video_title = content_block.get("title", "")
							lesson_doc.video_url = content_data.get("videoUrl", "")
							lesson_doc.video_description = content_data.get("description", "")
						elif content_type == "quiz":
							lesson_doc.quiz_title = content_block.get("title", "Quiz")
							lesson_doc.quiz_description = content_data.get("description", "")

						# Insert lesson to get proper naming
						lesson_doc.insert(ignore_permissions=True)

						lessons_created.append(
							{
								"name": lesson_doc.name,
								"type": content_type,
								"title": lesson_doc.title,
								"chapter": chapter_doc.name,
							}
						)

						# === Create Quiz Questions using Frappe API ===
						if content_type == "quiz" and "questions" in content_data:
							for q_idx, question_data in enumerate(content_data["questions"]):
								# Step 1: Create LMS Question first using Frappe API
								lms_question_doc = frappe.new_doc("LMS Question")
								lms_question_doc.question = question_data.get("question", "")
								lms_question_doc.type = "Choices"
								lms_question_doc.multiple = 0

								# Handle options array for multiple choice
								options = question_data.get("options", [])
								if len(options) > 0:
									lms_question_doc.option_1 = options[0]
								if len(options) > 1:
									lms_question_doc.option_2 = options[1]
								if len(options) > 2:
									lms_question_doc.option_3 = options[2]
								if len(options) > 3:
									lms_question_doc.option_4 = options[3]

								# Set correct answer
								correct_answer_index = question_data.get("correctAnswer", 0)
								lms_question_doc.is_correct_1 = 1 if correct_answer_index == 0 else 0
								lms_question_doc.is_correct_2 = 1 if correct_answer_index == 1 else 0
								lms_question_doc.is_correct_3 = 1 if correct_answer_index == 2 else 0
								lms_question_doc.is_correct_4 = 1 if correct_answer_index == 3 else 0

								# Insert LMS Question (will get auto-generated name like QTS-2024-00001)
								lms_question_doc.insert(ignore_permissions=True)

								# Step 2: Create LMS Quiz Question using Frappe API
								quiz_question_doc = frappe.new_doc("LMS Quiz Question")
								quiz_question_doc.question = lms_question_doc.name  # Link to LMS Question
								quiz_question_doc.marks = int(question_data.get("mark", 1))
								quiz_question_doc.question_type = "Multiple Choice"
								quiz_question_doc.points = int(question_data.get("mark", 1))
								quiz_question_doc.is_required = 0

								# Convert correct answer index to letter format
								correct_answer_letter = (
									["A", "B", "C", "D"][correct_answer_index]
									if correct_answer_index < 4
									else "A"
								)
								quiz_question_doc.correct_answer = correct_answer_letter

								# Set options for compatibility
								quiz_question_doc.option_a = options[0] if len(options) > 0 else ""
								quiz_question_doc.option_b = options[1] if len(options) > 1 else ""
								quiz_question_doc.option_c = options[2] if len(options) > 2 else ""
								quiz_question_doc.option_d = options[3] if len(options) > 3 else ""
								quiz_question_doc.explanation = question_data.get("explanation", "")

								# Set parent relationship
								quiz_question_doc.parent = lesson_doc.name
								quiz_question_doc.parenttype = "Course Lesson"
								quiz_question_doc.parentfield = "quiz_questions"
								quiz_question_doc.idx = q_idx + 1

								# Insert LMS Quiz Question (will get auto-generated name like QQ-281024-00001)
								quiz_question_doc.insert(ignore_permissions=True)

								quiz_questions_created.append(
									{
										"lms_question_name": lms_question_doc.name,
										"lms_question_autoname": lms_question_doc.name,  # Shows auto-generated name
										"quiz_question_name": quiz_question_doc.name,
										"quiz_question_autoname": quiz_question_doc.name,  # Shows auto-generated name
										"question": question_data.get("question", ""),
										"lesson": lesson_doc.name,
										"chapter": chapter_doc.name,
									}
								)

		# Commit all changes
		frappe.db.commit()

		return {
			"success": True,
			"message": "Course created successfully with chapters and lessons using proper Frappe naming",
			"data": {
				"course_name": course_doc.name,
				"course_title": course_doc.title,
				"pricing_model": data.get("pricingModel", "free"),
				"price": data.get("price", 0),
				"chapters_count": len(chapters_created),
				"lessons_count": len(lessons_created),
				"quiz_questions_count": len(quiz_questions_created),
				"chapters": chapters_created,
				"lessons": lessons_created,
				"quiz_questions_details": quiz_questions_created,
			},
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Course Creation Failed")
		return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def create_course_2():
	"""
	Create a comprehensive course with chapters, lessons, and settings.
	Uses Course Chapter and Course Lesson doctypes.
	Properly handles LMS Question → LMS Quiz Question relationship.
	"""
	import json

	from frappe.utils import generate_hash, now

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		creation_time = now()
		owner = frappe.session.user
		course_name = generate_hash(length=10)

		# === Create Course ===
		course_fields = {
			"name": course_name,
			"title": data.get("title", ""),
			"description": data.get("courseDescription", ""),
			"short_introduction": data.get("courseDescription", "")[:500],  # Truncate for short intro
			"image": data.get("thumbnailImage", ""),
			"video": data.get("introductoryVideo", ""),
			"tags": ",".join(data.get("tags", []))
			if isinstance(data.get("tags"), list)
			else data.get("tagCategory", ""),
			"category": data.get("category", ""),
			"education_level": data.get("educationLevel", ""),
			"course_language": data.get("courseLanguage", ""),
			"paid_course": 1 if data.get("pricingModel") == "paid" else 0,
			"course_price": data.get("price", 0) if data.get("pricingModel") == "paid" else 0,
			"currency": "USD" if data.get("pricingModel") == "paid" else "",
			"requirement": data.get("requirements", ""),
			"objectives": data.get("courseObjective", ""),
			"published": 1 if data.get("visibility") == "public" else 0,
			"enable_certification": 1 if data.get("issueCertificate", False) else 0,
			"creation": creation_time,
			"modified": creation_time,
			"modified_by": owner,
			"owner": owner,
			"docstatus": 0,
		}

		# Insert course
		frappe.db.sql(
			"""
			INSERT INTO `tabLMS Course`
			(name, title, description, short_introduction, image, video, tags, category,
			 education_level, course_language, paid_course, course_price, currency,
			 requirement, objectives, published, enable_certification, creation, modified,
			 modified_by, owner, docstatus)
			VALUES
			(%(name)s, %(title)s, %(description)s, %(short_introduction)s, %(image)s, %(video)s,
			 %(tags)s, %(category)s, %(education_level)s, %(course_language)s, %(paid_course)s,
			 %(course_price)s, %(currency)s, %(requirement)s, %(objectives)s, %(published)s,
			 %(enable_certification)s, %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, %(docstatus)s)
		""",
			course_fields,
		)

		# === Add Instructor (auto-populate current user) ===
		instructor_name = generate_hash(length=10)
		frappe.db.sql(
			"""
			INSERT INTO `tabCourse Instructor`
			(name, instructor, parent, parenttype, parentfield, idx, creation, modified,
			 modified_by, owner, docstatus)
			VALUES
			(%(name)s, %(instructor)s, %(parent)s, 'LMS Course', 'instructors', 1,
			 %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
		""",
			{
				"name": instructor_name,
				"instructor": data.get("instructor", owner),  # Use provided instructor or current user
				"parent": course_name,
				"creation": creation_time,
				"modified": creation_time,
				"modified_by": owner,
				"owner": owner,
			},
		)

		# === Create Chapters and Lessons ===
		chapters_created = []
		lessons_created = []
		quiz_questions_created = []

		if "modules" in data:
			for chapter_idx, module_data in enumerate(data["modules"]):
				chapter_name = generate_hash(length=10)
				chapters_created.append(
					{
						"name": chapter_name,
						"title": module_data.get("title", ""),
						"description": module_data.get("description", ""),
					}
				)

				# Insert Course Chapter
				frappe.db.sql(
					"""
					INSERT INTO `tabCourse Chapter`
					(name, course, title, description, idx, creation, modified,
					 modified_by, owner, docstatus)
					VALUES
					(%(name)s, %(course)s, %(title)s, %(description)s, %(idx)s,
					 %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
				""",
					{
						"name": chapter_name,
						"course": course_name,
						"title": module_data.get("title", ""),
						"description": module_data.get("description", ""),
						"idx": chapter_idx + 1,
						"creation": creation_time,
						"modified": creation_time,
						"modified_by": owner,
						"owner": owner,
					},
				)

				# === Create Course Lessons ===
				if "contentBlocks" in module_data:
					for block_idx, content_block in enumerate(module_data["contentBlocks"]):
						lesson_name = generate_hash(length=10)
						content_type = content_block.get("type", "Lesson")
						content_data = content_block.get("data", {})

						lessons_created.append(
							{
								"name": lesson_name,
								"type": content_type,
								"title": content_block.get("title", ""),
								"chapter": chapter_name,
							}
						)

						# Prepare lesson fields based on content type
						lesson_fields = {
							"name": lesson_name,
							"chapter": chapter_name,
							"course": course_name,
							"title": content_block.get("title", ""),
							"content_type": content_type.title(),
							"content_order": block_idx + 1,
							"is_published": 1,
							"creation": creation_time,
							"modified": creation_time,
							"modified_by": owner,
							"owner": owner,
						}

						if content_type == "essay":
							lesson_fields.update(
								{
									"essay_title": content_block.get("title", ""),
									"essay_content": content_data.get("content", ""),
								}
							)
						elif content_type == "video":
							lesson_fields.update(
								{
									"video_title": content_block.get("title", ""),
									"video_url": content_data.get("videoUrl", ""),
									"video_description": content_data.get("description", ""),
								}
							)
						elif content_type == "quiz":
							lesson_fields.update(
								{
									"quiz_title": content_block.get("title", "Quiz"),
									"quiz_description": content_data.get("description", ""),
								}
							)

						# Insert Course Lesson
						frappe.db.sql(
							"""
							INSERT INTO `tabCourse Lesson`
							(name, chapter, course, title, content_type, content_order, is_published,
							 essay_title, essay_content, video_title, video_url, video_description,
							 quiz_title, quiz_description, creation, modified, modified_by, owner, docstatus)
							VALUES
							(%(name)s, %(chapter)s, %(course)s, %(title)s, %(content_type)s, %(content_order)s,
							 %(is_published)s, %(essay_title)s, %(essay_content)s, %(video_title)s,
							 %(video_url)s, %(video_description)s, %(quiz_title)s, %(quiz_description)s,
							 %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
						""",
							{
								"name": lesson_name,
								"chapter": chapter_name,
								"course": course_name,
								"title": content_block.get("title", ""),
								"content_type": content_type.title(),
								"content_order": block_idx + 1,
								"is_published": 1,
								"essay_title": lesson_fields.get("essay_title", ""),
								"essay_content": lesson_fields.get("essay_content", ""),
								"video_title": lesson_fields.get("video_title", ""),
								"video_url": lesson_fields.get("video_url", ""),
								"video_description": lesson_fields.get("video_description", ""),
								"quiz_title": lesson_fields.get("quiz_title", ""),
								"quiz_description": lesson_fields.get("quiz_description", ""),
								"creation": creation_time,
								"modified": creation_time,
								"modified_by": owner,
								"owner": owner,
							},
						)

						# === Create Quiz Questions (First create LMS Question, then LMS Quiz Question) ===
						if content_type == "quiz" and "questions" in content_data:
							for q_idx, question_data in enumerate(content_data["questions"]):
								# Step 1: Create LMS Question first
								lms_question_name = generate_hash(length=10)

								# Handle options array for multiple choice
								options = question_data.get("options", [])
								option_1 = options[0] if len(options) > 0 else ""
								option_2 = options[1] if len(options) > 1 else ""
								option_3 = options[2] if len(options) > 2 else ""
								option_4 = options[3] if len(options) > 3 else ""

								# Determine which options are correct
								correct_answer_index = question_data.get("correctAnswer", 0)
								is_correct_1 = 1 if correct_answer_index == 0 else 0
								is_correct_2 = 1 if correct_answer_index == 1 else 0
								is_correct_3 = 1 if correct_answer_index == 2 else 0
								is_correct_4 = 1 if correct_answer_index == 3 else 0

								# Insert LMS Question
								frappe.db.sql(
									"""
									INSERT INTO `tabLMS Question`
									(name, question, type, multiple, option_1, is_correct_1, option_2, is_correct_2,
									 option_3, is_correct_3, option_4, is_correct_4, creation, modified,
									 modified_by, owner, docstatus)
									VALUES
									(%(name)s, %(question)s, 'Choices', 0, %(option_1)s, %(is_correct_1)s,
									 %(option_2)s, %(is_correct_2)s, %(option_3)s, %(is_correct_3)s,
									 %(option_4)s, %(is_correct_4)s, %(creation)s, %(modified)s,
									 %(modified_by)s, %(owner)s, 0)
								""",
									{
										"name": lms_question_name,
										"question": question_data.get("question", ""),
										"option_1": option_1,
										"is_correct_1": is_correct_1,
										"option_2": option_2,
										"is_correct_2": is_correct_2,
										"option_3": option_3,
										"is_correct_3": is_correct_3,
										"option_4": option_4,
										"is_correct_4": is_correct_4,
										"creation": creation_time,
										"modified": creation_time,
										"modified_by": owner,
										"owner": owner,
									},
								)

								# Step 2: Create LMS Quiz Question that links to the LMS Question
								quiz_question_name = generate_hash(length=10)

								# Convert correct answer index to letter format for LMS Quiz Question
								correct_answer_letter = (
									["A", "B", "C", "D"][correct_answer_index]
									if correct_answer_index < 4
									else "A"
								)

								frappe.db.sql(
									"""
									INSERT INTO `tabLMS Quiz Question`
									(name, question, marks, question_type, points, is_required, correct_answer,
									 option_a, option_b, option_c, option_d, explanation, parent, parenttype,
									 parentfield, idx, creation, modified, modified_by, owner, docstatus)
									VALUES
									(%(name)s, %(question_link)s, %(marks)s, 'Multiple Choice', %(points)s, 0,
									 %(correct_answer)s, %(option_a)s, %(option_b)s, %(option_c)s, %(option_d)s,
									 %(explanation)s, %(parent)s, 'Course Lesson', 'quiz_questions', %(idx)s,
									 %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
								""",
									{
										"name": quiz_question_name,
										"question_link": lms_question_name,  # Link to the LMS Question
										"marks": int(question_data.get("mark", 1)),
										"points": int(question_data.get("mark", 1)),
										"correct_answer": correct_answer_letter,
										"option_a": option_1,
										"option_b": option_2,
										"option_c": option_3,
										"option_d": option_4,
										"explanation": question_data.get("explanation", ""),
										"parent": lesson_name,
										"idx": q_idx + 1,
										"creation": creation_time,
										"modified": creation_time,
										"modified_by": owner,
										"owner": owner,
									},
								)

								quiz_questions_created.append(
									{
										"lms_question_name": lms_question_name,
										"quiz_question_name": quiz_question_name,
										"question": question_data.get("question", ""),
										"lesson": lesson_name,
										"chapter": chapter_name,
									}
								)

		# Commit all changes
		frappe.db.commit()

		return {
			"success": True,
			"message": "Course created successfully with chapters and lessons",
			"data": {
				"course_name": course_name,
				"course_title": data.get("title", ""),
				"pricing_model": data.get("pricingModel", "free"),
				"price": data.get("price", 0),
				"chapters_count": len(chapters_created),
				"lessons_count": len(lessons_created),
				"quiz_questions_count": len(quiz_questions_created),
				"chapters": chapters_created,
				"quiz_questions_details": quiz_questions_created,
			},
		}

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Course Creation Failed")
		return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist(allow_guest=True)
def get_course_detail_new(course_name):
	"""
	Fetch a course with its chapters and lessons using Frappe API.
	"""
	try:
		# Get course basic info using Frappe API
		if not frappe.db.exists("LMS Course", course_name):
			return {"error": "Course not found"}

		course_doc = frappe.get_doc("LMS Course", course_name)
		course = {
			"doctype": "LMS Course",
			"name": course_doc.name,
			"title": course_doc.title,
			"description": course_doc.description,
			"image": course_doc.image,
			"video": getattr(course_doc, "video", ""),
			"tags": course_doc.tags,
			"category": getattr(course_doc, "category", ""),
			"education_level": course_doc.education_level,
			"course_language": course_doc.course_language,
			"paid_course": course_doc.paid_course,
			"course_price": course_doc.course_price,
			"currency": course_doc.currency,
			"requirement": course_doc.requirement,
			"objectives": getattr(course_doc, "objectives", ""),
			"published": course_doc.published,
			"enable_certification": course_doc.enable_certification,
		}

		# Get chapters using Frappe API
		try:
			chapters = frappe.get_all(
				"Course Chapter",
				filters={"course": course_name},
				fields=["name", "title", "idx"],
				order_by="idx",
			)
		except Exception as e:
			frappe.log_error(f"Course Chapter query failed: {str(e)}", "get_course_detail")
			chapters = []

		chapters_data = []
		for chapter in chapters:
			try:
				# Get lessons for each chapter using Frappe API
				lesson_fields = ["name", "title", "content_type", "content_order", "is_published"]

				# Add enhanced fields if they exist
				try:
					# Test if enhanced fields exist by trying a small query first
					test_lesson = frappe.get_all(
						"Course Lesson", filters={"chapter": chapter["name"]}, fields=["name"], limit=1
					)

					if test_lesson:
						# If lessons exist, try to get enhanced fields
						enhanced_fields = [
							"essay_title",
							"essay_content",
							"video_title",
							"video_url",
							"video_description",
							"video_content",
							"quiz_title",
							"quiz_description",
							"body",
							"content",
							"youtube",
							"quiz_id",
						]
						lesson_fields.extend(enhanced_fields)
				except Exception:
					pass  # Use basic fields only

				lessons = frappe.get_all(
					"Course Lesson",
					filters={"chapter": chapter["name"]},
					fields=lesson_fields,
					order_by="content_order, idx",
				)

			except Exception as e:
				frappe.log_error(f"Course Lesson query failed: {str(e)}", "get_course_detail")
				# Fallback to basic lesson fields
				try:
					lessons = frappe.get_all(
						"Course Lesson",
						filters={"chapter": chapter["name"]},
						fields=["name", "title"],
						order_by="idx",
					)
				except Exception:
					lessons = []

			# Process lessons and get quiz questions
			lessons_data = []
			for lesson in lessons:
				lesson_data = {
					"name": lesson.get("name"),
					"title": lesson.get("title"),
					"content_type": lesson.get("content_type", "Lesson"),
					"content_order": lesson.get("content_order", 1),
					"is_published": lesson.get("is_published", 1),
				}

				# Add enhanced content fields if available
				if lesson.get("content_type") == "Essay":
					lesson_data["essay_title"] = lesson.get("essay_title", "")
					lesson_data["essay_content"] = lesson.get("essay_content", "")
				elif lesson.get("content_type") == "Video":
					lesson_data["video_title"] = lesson.get("video_title", "")
					lesson_data["video_url"] = lesson.get("video_url", "")
					lesson_data["video_description"] = lesson.get("video_description", "")
					lesson_data["video_content"] = lesson.get("video_content", "")
					lesson_data["youtube"] = lesson.get("youtube", "")
				elif lesson.get("content_type") == "Quiz":
					lesson_data["quiz_title"] = lesson.get("quiz_title", "")
					lesson_data["quiz_description"] = lesson.get("quiz_description", "")

					# Get quiz questions using Frappe API
					try:
						questions = frappe.get_all(
							"LMS Quiz Question",
							filters={"parent": lesson["name"], "parenttype": "Course Lesson"},
							fields=[
								"name",
								"question",
								"option_a",
								"option_b",
								"option_c",
								"option_d",
								"correct_answer",
								"marks",
							],
							order_by="idx",
						)

						# Convert question links to actual question text
						for question in questions:
							if question.get("question"):
								try:
									# If question is a link to LMS Question, get the actual question text
									if frappe.db.exists("LMS Question", question["question"]):
										lms_question = frappe.get_doc("LMS Question", question["question"])
										question["question_text"] = lms_question.question
									else:
										question["question_text"] = question["question"]
								except Exception:
									question["question_text"] = question["question"]

						lesson_data["questions"] = questions
					except Exception as e:
						frappe.log_error(f"Quiz Questions query failed: {str(e)}", "get_course_detail")
						lesson_data["questions"] = []
				else:
					# Default lesson content
					lesson_data["body"] = lesson.get("body", "")
					lesson_data["content"] = lesson.get("content", "")
					lesson_data["youtube"] = lesson.get("youtube", "")
					lesson_data["quiz_id"] = lesson.get("quiz_id", "")

				lessons_data.append(lesson_data)

			chapter_data = {
				"name": chapter["name"],
				"title": chapter["title"],
				"description": "",  # Course Chapter doesn't have description field
				"idx": chapter["idx"],
				"lessons": lessons_data,
			}
			chapters_data.append(chapter_data)

		return {
			"success": True,
			"data": {"course": course, "chapters": chapters_data},
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Course Detail Failed")
		return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_published_courses(limit=10, page=1):
	"""
	Get published courses with pagination using Frappe API.
	"""
	try:
		limit = int(limit)
		page = int(page)
		offset = (page - 1) * limit

		# Get total count using Frappe API
		total_courses = frappe.db.count("LMS Course", {"published": 1})
		total_pages = (total_courses + limit - 1) // limit

		# Get course names using Frappe API
		course_names = frappe.get_all(
			"LMS Course",
			filters={"published": 1},
			fields=["name"],
			limit=limit,
			start=offset,
			order_by="creation desc",
		)

		# Serialize each course
		courses = []
		for course_name_obj in course_names:
			try:
				course_data = serialize_course(course_name_obj["name"])
				courses.append(course_data)
			except Exception as e:
				frappe.log_error(
					f"Failed to serialize course {course_name_obj['name']}: {str(e)}", "get_published_courses"
				)
				continue

		return paginated_response(courses, page, total_pages, total_courses)

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Published Courses Failed")
		return {"error": str(e), "success": False}

@frappe.whitelist()
def get_tutor_courses_with_enrollments(tutor, course_name=None, status=None):
	"""
	Get all students enrolled in courses where the tutor is an instructor.
	Returns flattened student data with course information.
	"""
	try:
		# Step 1: Get all course names where tutor is instructor using Frappe API
		course_instructor_filters = {"instructor": tutor}
		course_names = frappe.get_all(
			"Course Instructor", filters=course_instructor_filters, fields=["parent"], pluck="parent"
		)

		if not course_names:
			return {"success": True, "data": [], "count": 0}

		# Step 2: Filter by course_name and status if provided using Frappe API
		course_filters = {"name": ["in", course_names]}
		if course_name:
			course_filters["name"] = course_name
		if status:
			course_filters["status"] = status

		# Get filtered courses
		filtered_courses = frappe.get_all("LMS Course", filters=course_filters, fields=["name", "title", "course_price", "currency"])

		if not filtered_courses:
			return {"success": True, "data": [], "count": 0}

		students_data = []
		student_counter = 1

		for course in filtered_courses:
			try:
				# Get enrolled students for this course using Frappe API
				enrollments = frappe.get_all(
					"LMS Enrollment",
					filters={"course": course["name"]},
					fields=["member", "creation", "member_name", "progress"]
				)

				if enrollments:
					for enrollment in enrollments:
						try:
							# Get user profile data
							user_profile = frappe.get_value(
								"User Profile", {"user": enrollment["member"]}, "*", as_dict=True
							)

							# Get basic user data as fallback
							user_info = frappe.get_value(
								"User", enrollment["member"], ["name", "full_name", "email", "user_image"], as_dict=True
							)

							if user_profile or user_info:
								# Determine student name (prefer full_name from User, fallback to User Profile)
								student_name = ""
								if user_info and user_info.get("full_name"):
									student_name = user_info["full_name"]
								elif user_profile and user_profile.get("user"):
									# Try to get full_name from the linked user
									linked_user = frappe.get_value("User", user_profile["user"], "full_name")
									student_name = linked_user or user_profile.get("user", "")
								else:
									student_name = enrollment["member"]

								# Get education level from User Profile
								education_level = user_profile.get("education_level", "Not Specified") if user_profile else "Not Specified"

								# Create student record in desired format
								student_record = {
									"id": user_info.get("email", "") if user_info else "",
									"name": student_name,
									"avatar": user_info.get("user_image"),
									"educationLevel": (
										{
											"id": user_profile.get("education_level"),
											"name": frappe.db.get_value(
												"LMS Course Level",
												user_profile.get("education_level"),
												"education_level"
											)
										}
									),
									"enrolledCourse": course.get("title", ""),
									"progress": enrollment.get("progress", 0),
									"dateEnrolled": enrollment.get("creation"),
									"courseFee": course.get("course_price"),
									"currency": course.get("currency"),
									"email": user_info.get("email", "") if user_info else "",
									"course_id": course["name"],
									"student_id": enrollment["member"]
								}

								students_data.append(student_record)
								student_counter += 1

						except Exception as e:
							frappe.log_error(
								f"Failed to process student {enrollment['member']}: {str(e)}",
								"get_tutor_courses_with_enrollments",
							)
							continue

			except Exception as e:
				frappe.log_error(
					f"Failed to process course {course['name']}: {str(e)}", "get_tutor_courses_with_enrollments"
				)
				continue

		return {"success": True, "data": students_data, "count": len(students_data)}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Tutor Courses With Enrollments Failed")
		return {"error": str(e), "success": False}

@frappe.whitelist(allow_guest=True)
def get_course_detail(course_name):
	"""
	Fetch a course with its chapters and lessons using Frappe API.
	Adds enrollment status for the current session user.
	"""
	try:
		if not frappe.db.exists("LMS Course", course_name):
			return {"error": "Course not found"}

		course_data = serialize_course_new(course_name)
		if course_data is None:
			return {"error": "Failed to serialize course data"}

		# Determine enrollment status for logged-in user
		session_user = frappe.session.user
		if session_user and session_user != "Guest":
			is_enrolled = frappe.db.exists(
				"LMS Enrollment",
				{
					"course": course_name,
					"member": session_user,
					"member_type": "Student"
				}
			)
			course_data["enrollment_status"] = "enrolled" if is_enrolled else "not_enrolled"
		else:
			course_data["enrollment_status"] = "not_enrolled"

		return {
			"success": True,
			"data": course_data
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Get Course Detail Failed")
		return {"error": str(e)}

def serialize_course_new(course_name):
	"""Return a structured course with profile, chapters, and lessons"""
	try:
		course = frappe.get_doc("LMS Course", course_name)

		# Instructor(s) - with safe field access
		instructors = []
		try:
			instructor_links = frappe.get_all(
				"Course Instructor",
				filters={"parent": course.name},
				fields=["instructor"]
			)

			for inst in instructor_links:
				try:
					profile_data = frappe.get_value(
						"User Profile",
						{"user": inst["instructor"]},
						"*",
						as_dict=True
					)
					if profile_data:
						user_doc = frappe.get_doc("User", profile_data["user"])
						instructors.append({
							""
							"id": profile_data.name,
							"full_name": getattr(user_doc, "full_name", ""),
							"email": getattr(user_doc, "email", ""),
							"phone_number": getattr(profile_data, "phone_number", ""),
							"profile_image_url": getattr(user_doc, "user_image", ""),
							"bio": getattr(profile_data, "bio", ""),
							"rating": getattr(profile_data, "rating", 0),
							"experience_years": getattr(profile_data, "teaching_experience", 0),
							"subjects": json.loads(profile_data.subjects) if getattr(profile_data, "subjects", None) else [],
						})
				except Exception as e:
					frappe.log_error(f"Failed to fetch instructor: {str(e)}", "serialize_course")
					continue
		except Exception as e:
			frappe.log_error(f"Failed to fetch instructors: {str(e)}", "serialize_course")

		# Reviews - with safe field access
		reviews_list = []
		try:
			reviews = frappe.get_all(
				"LMS Course Review",
				filters={"course": course.name},
				fields=["name", "rating", "review", "owner", "creation"]
			)

			for r in reviews:
				try:
					reviewer_name = ""
					reviewer_image = ""
					if r.get("owner"):
						reviewer_data = frappe.get_all(
							"User",
							filters={"name": r.owner},
							fields=["full_name", "user_image"],
							limit=1
						)
						if reviewer_data:
							reviewer_name = reviewer_data[0].get("full_name", "")
							reviewer_image = reviewer_data[0].get("user_image", "")

					reviews_list.append({
						"id": r.name,
						"reviewer_name": reviewer_name,
						"reviewer_image": reviewer_image,
						"rating": r.get("rating", 0),
						"comment": r.get("review", ""),
						"date": r.get("creation", ""),
					})
				except Exception as e:
					frappe.log_error(f"Failed to process review: {str(e)}", "serialize_course")
					continue
		except Exception as e:
			frappe.log_error(f"Failed to fetch reviews: {str(e)}", "serialize_course")

		# Subject - with safe field access
		subject = None
		try:
			if getattr(course, "subject", None):
				if frappe.db.exists("Subject", course.subject):
					subject_doc = frappe.get_doc("Subject", course.subject)
					subject = {
						"name": subject_doc.name,
						"subject_name": getattr(subject_doc, "subject_name", ""),
					}
		except Exception as e:
			frappe.log_error(f"Failed to fetch subject: {str(e)}", "serialize_course")

		# Educational Level - with safe field access
		education_level = None
		try:
			course_level = getattr(course, "course_level", None) or getattr(course, "education_level", None)
			if course_level:
				if frappe.db.exists("LMS Course Level", course_level):
					education_level_doc = frappe.get_doc("LMS Course Level", course_level)
					education_level = {
						"name": education_level_doc.name,
						"level_name": getattr(education_level_doc, "education_level", ""),
					}
		except Exception as e:
			frappe.log_error(f"Failed to fetch education level: {str(e)}", "serialize_course")

		# Chapters & Lessons - with safe field access and fallbacks
		chapters_list = []
		try:
			chapters = frappe.get_all(
				"Course Chapter",
				filters={"course": course.name},
				fields=["name", "title", "idx"],
				order_by="idx"
			)
		except Exception as e:
			frappe.log_error(f"Course Chapter query failed: {str(e)}", "serialize_course")
			chapters = []

		for chapter in chapters:
			# Determine available lesson fields dynamically
			lesson_fields = ["name", "title", "content_type", "content_order", "is_published"]

			try:
				# Test if enhanced fields exist
				test_lesson = frappe.get_all(
					"Course Lesson",
					filters={"chapter": chapter.name},
					fields=["name"],
					limit=1
				)

				if test_lesson:
					enhanced_fields = [
						"essay_title", "essay_content",
						"video_title", "video_url", "video_description", "video_content",
						"quiz_title", "quiz_description",
						"body", "content", "youtube", "quiz_id"
					]
					lesson_fields.extend(enhanced_fields)
			except Exception:
				pass  # Use basic fields only

			# Fetch lessons
			try:
				lessons = frappe.get_all(
					"Course Lesson",
					filters={"chapter": chapter.name},
					fields=lesson_fields,
					order_by="content_order, idx",
				)
			except Exception as e:
				frappe.log_error(f"Course Lesson query failed: {str(e)}", "serialize_course")
				try:
					lessons = frappe.get_all(
						"Course Lesson",
						filters={"chapter": chapter.name},
						fields=["name", "title"],
						order_by="idx",
					)
				except:
					lessons = []

			lessons_list = []
			for lesson in lessons:
				lesson_data = {
					"id": lesson.get("name"),
					"title": lesson.get("title", ""),
					"content_type": lesson.get("content_type", "Lesson"),
					"content_order": lesson.get("content_order", 1),
					"is_published": lesson.get("is_published", 1),
				}

				# Handle Quiz questions
				if lesson.get("content_type") == "Quiz":
					quiz_questions = []
					try:
						questions = frappe.get_all(
							"LMS Quiz Question",
							filters={"parent": lesson["name"], "parenttype": "Course Lesson"},
							fields=[
								"name", "question", "question_type",
								"option_a", "option_b", "option_c", "option_d",
								"correct_answer", "marks"
							],
							order_by="idx",
						)

						# Convert question links to actual question text
						for question in questions:
							if question.get("question"):
								try:
									if frappe.db.exists("LMS Question", question["question"]):
										lms_question = frappe.get_doc("LMS Question", question["question"])
										question["question_text"] = getattr(lms_question, "question", question["question"])
									else:
										question["question_text"] = question["question"]
								except Exception:
									question["question_text"] = question["question"]
							quiz_questions.append(question)
					except Exception as e:
						frappe.log_error(f"Quiz Questions query failed: {str(e)}", "serialize_course")

					lesson_data["quiz"] = {
						"title": lesson.get("quiz_title", ""),
						"description": lesson.get("quiz_description", ""),
						"questions": quiz_questions,
						"quiz_id": lesson.get("quiz_id", ""),
					}

				elif lesson.get("content_type") == "Essay":
					lesson_data["essay"] = {
						"title": lesson.get("essay_title", ""),
						"content": lesson.get("essay_content", ""),
					}

				elif lesson.get("content_type") == "Video":
					lesson_data["video"] = {
						"title": lesson.get("video_title", ""),
						"description": lesson.get("video_description", ""),
						"url": lesson.get("video_content") or lesson.get("video_url", ""),
						"youtube_url": lesson.get("youtube", ""),
					}

				else:  # Default Lesson type
					lesson_data["lesson"] = {
						"body": lesson.get("body", ""),
						"content": lesson.get("content", ""),
						"youtube_url": lesson.get("youtube", ""),
						"quiz_id": lesson.get("quiz_id", ""),
					}

				lessons_list.append(lesson_data)

			chapters_list.append({
				"id": chapter.name,
				"title": chapter.get("title", ""),
				"description": chapter.get("description", ""),
				"idx": chapter.get("idx", 0),
				"lessons": lessons_list,
			})

		# Final Structured Response with safe field access
		return {
			"doctype": "LMS Course",
			"id": course.name,
			"title": getattr(course, "title", ""),
			# "tags": getattr(course, "tags", ""),
			"tags": [tag.strip() for tag in getattr(course, "tags", "").split(",") if tag.strip()],
			"status": getattr(course, "status", ""),
			"image": getattr(course, "image", ""),
			"published": getattr(course, "published", 0),
			"published_on": getattr(course, "published_on", None),
			"featured": getattr(course, "featured", 0),
			"short_introduction": getattr(course, "short_introduction", ""),
			"description": getattr(course, "description", ""),
			"requirement": getattr(course, "requirement", ""),
			"objectives": getattr(course, "objectives", ""),
			"course_language": getattr(course, "course_language", ""),
			"education_level": education_level,
			"subject": subject,
			"paid_course": getattr(course, "paid_course", 0),
			"price": getattr(course, "course_price", 0),
			"currency": getattr(course, "currency", ""),
			"rating": getattr(course, "rating", 0),
			"enrollments": getattr(course, "enrollments", 0),
			"enable_certification": getattr(course, "enable_certification", 0),
			"instructors": instructors,
			"reviews": reviews_list,
			"chapters": chapters_list,
			"introductory_video": getattr(course, "video", "")
		}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Serialize Course Failed")
		return None
