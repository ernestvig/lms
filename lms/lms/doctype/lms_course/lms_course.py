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
			self.status = "Approved"

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
	"""Get all courses for a given instructor"""

	fields = ["*"]

	filters = {"host_user": tutor}
	if published:
		filters["published"] = published
	if is_draft:
		filters["is_drafted"] = is_draft

	limit = int(limit) if limit else 100

	# Step 1: Get all course names linked to instructor
	course_names = frappe.get_all("Course Instructor", filters={"instructor": tutor}, pluck="parent")

	if not course_names:
		return []

	# Step 2: Get courses
	courses = frappe.get_list(
		"LMS Course",
		filters={"name": ["in", course_names]},
		fields=fields,
		limit=limit,
		order_by="modified desc",
	)

	profile_data = {}
	if frappe.db.exists("User Profile", {"user": tutor}):
		profile_doc = frappe.get_doc("User Profile", {"user": tutor})
		profile_data = profile_doc.as_dict()

	return {
		"success": True,
		"data": [{**course, "profile": profile_data} for course in courses],
		"count": len(courses),
	}


@frappe.whitelist(allow_guest=True)
def get_all_courses():
	limit = int(frappe.form_dict.get("limit", 100))
	course_names = frappe.get_all("LMS Course", fields=["name"], limit=limit, order_by="modified desc")

	courses = [serialize_course(c["name"]) for c in course_names]

	return {"success": True, "data": courses, "count": len(courses)}


def serialize_course(course_name):
	"""Return a fully-hydrated course with profile, modules, and content"""
	course = frappe.get_doc("LMS Course", course_name)
	course_dict = course.as_dict()

	# Instructor
	instructors = frappe.get_all("Course Instructor", filters={"parent": course.name}, fields=["instructor"])
	if instructors:
		profile_data = (
			frappe.get_value("User Profile", {"user": instructors[0]["instructor"]}, "*", as_dict=True) or {}
		)
		course_dict["profile"] = profile_data
	else:
		course_dict["profile"] = {}

	# Expand modules
	for module in course_dict.get("modules", []):
		if module.get("modules"):
			content = (
				frappe.get_value("LMS Course Module Content", {"name": module["modules"]}, "*", as_dict=True)
				or {}
			)
			if content.get("content_type") == "Quiz":
				questions = frappe.get_all(
					"LMS Quiz Question", filters={"parent": content["name"]}, fields=["*"]
				)
				content["quiz_questions"] = questions
			module["module_content"] = content
		else:
			module["module_content"] = {}

	return course_dict


@frappe.whitelist(allow_guest=True)
def get_course_detail(course_name):
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
	Create a Course with Modules, Instructors, Content (Essay/Video/Quiz),
	and Quiz Questions.
	"""
	import json

	try:
		data = {}
		if frappe.request and frappe.request.data:
			data = json.loads(frappe.request.data)

		# === Create Course ===
		course_doc = frappe.new_doc("LMS Course")

		# Map top-level fields
		for field in [
			"title",
			"tags",
			"status",
			"image",
			"published",
			"published_on",
			"upcoming",
			"featured",
			"disable_self_learning",
			"short_introduction",
			"description",
			"paid_course",
			"enable_certification",
			"paid_certificate",
			"course_price",
			"currency",
			"amount_usd",
			"enrollments",
			"lessons",
			"rating",
			"course_language",
			"price",
			"introduction_video",
			"requirement",
			"education_level",
			"subject",
			"draft",
		]:
			if field in data:
				course_doc.set(field, data[field])

		# === Add Instructors (child table) ===
		if "instructors" in data:
			for inst in data["instructors"]:
				course_doc.append("instructors", {"instructor": inst.get("instructor")})

		# Save course first (so it has a name)
		course_doc.insert(ignore_permissions=True)

		# === Add Modules ===
		if "modules" in data:
			for mod in data["modules"]:
				module_doc = frappe.new_doc("Course Module")
				module_doc.parent = course_doc.name
				module_doc.parenttype = "LMS Course"
				module_doc.parentfield = "modules"
				module_doc.title = mod.get("title")
				module_doc.description = mod.get("description")
				module_doc.insert(ignore_permissions=True)

				# === Add Module Contents ===
				if "module_content" in mod:
					for content in mod["module_content"]:
						content_doc = frappe.new_doc("LMS Course Module Content")
						content_doc.parent = module_doc.name
						content_doc.parenttype = "Course Module"
						content_doc.parentfield = "module_content"
						content_doc.content_type = content.get("content_type")
						content_doc.essay_title = content.get("essay_title")
						content_doc.essay_content = content.get("essay_content")
						content_doc.video_title = content.get("video_title")
						content_doc.video_description = content.get("video_description")
						content_doc.video_file = content.get("video_file")
						content_doc.video_filename = content.get("video_filename")
						content_doc.quiz_title = content.get("quiz_title")
						content_doc.quiz_description = content.get("quiz_description")
						content_doc.insert(ignore_permissions=True)

						# === If Quiz, add Questions ===
						if content.get("content_type") == "Quiz" and "quiz_questions" in content:
							for q in content["quiz_questions"]:
								q_doc = frappe.new_doc("LMS Quiz Question")
								q_doc.parent = content_doc.name
								q_doc.parenttype = "Module Content"
								q_doc.parentfield = "quiz_questions"
								q_doc.question = q.get("question")
								q_doc.question_type = q.get("question_type")
								q_doc.option_a = q.get("option_a")
								q_doc.option_b = q.get("option_b")
								q_doc.option_c = q.get("option_c")
								q_doc.option_d = q.get("option_d")
								q_doc.correct_answer = q.get("correct_answer")
								q_doc.marks = q.get("marks")
								q_doc.points = q.get("points")
								q_doc.insert(ignore_permissions=True)

		frappe.db.commit()

		return {"success": True, "message": "Course created successfully", "course_name": course_doc.name}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Create Course Failed")
		return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_published_courses(limit=10, page=1):
	limit = int(limit)
	page = int(page)
	offset = (page - 1) * limit

	total_courses = frappe.db.count("LMS Course", {"published": 1})
	total_pages = (total_courses + limit - 1) // limit

	course_names = frappe.get_all(
		"LMS Course",
		filters={"published": 1},
		fields=["name"],
		limit=limit,
		start=offset,
		order_by="modified desc",
	)

	courses = [serialize_course(c["name"]) for c in course_names]

	return paginated_response(courses, page, total_pages, total_courses)


@frappe.whitelist()
# Get Tutor Enrolled Courses and Count
def get_tutor_enrolled_courses(tutor):
	# Get all unique course names where the tutor is enrolled as a student
	course_names = frappe.get_all(
		"LMS Enrollment", filters={"member": tutor, "member_type": "Student"}, distinct=True, pluck="course"
	)

	# Fetch detailed course information for each course name
	courses = [serialize_course(course_name) for course_name in course_names]

	return {"success": True, "data": courses, "count": len(courses)}


# @frappe.whitelist(allow_guest=True)
# def generate_presigned_url():
#     import re
#     try:
#         # Parse input
#         if frappe.request and frappe.request.data:
#             try:
#                 data = json.loads(frappe.request.data)
#             except Exception:
#                 data = frappe.form_dict
#         else:
#             data = frappe.form_dict
#
#         # Get and validate required fields
#         filename = data.get("filename")
#         folder = data.get("folder")
#         file_type = data.get("file_type")
#
#         # Check if any field is None or empty after stripping
#         if not filename or not str(filename).strip():
#             frappe.throw("Missing or empty filename")
#         if not folder or not str(folder).strip():
#             frappe.throw("Missing or empty folder")
#         if not file_type or not str(file_type).strip():
#             frappe.throw("Missing or empty file_type")
#
#         # Convert to strings and strip whitespace
#         filename = str(filename).strip()
#         folder = str(folder).strip()
#         file_type = str(file_type).strip()
#
#         # Validate file_type is a valid MIME type
#         if not re.match(r'^[\w\-\+\.]+/[\w\-\+\.]+$', file_type):
#             frappe.throw(f"Invalid file_type format: {file_type}")
#
#         # DEBUG: Get AWS configuration and log what we find
#         bucket_name = frappe.conf.get("aws_s3_bucket")
#         region = frappe.conf.get("aws_region")
#         aws_access_key_id = frappe.conf.get("aws_access_key_id")
#         aws_secret_access_key = frappe.conf.get("aws_secret_access_key")
#
#         # # DEBUG: Log the configuration values (mask sensitive data)
#         # frappe.log_error(f"""
#         # AWS Config Debug:
#         # - bucket_name: {bucket_name}
#         # - region: {region}
#         # - aws_access_key_id: {aws_access_key_id[:10] + '...' if aws_access_key_id else 'None'}
#         # - aws_secret_access_key: {'[SET]' if aws_secret_access_key else 'None'}
#         # - All frappe.conf keys: {list(frappe.conf.keys())}
#         # """, "AWS Config Debug")
#
#         # Try alternative configuration keys that might be used
#         if not bucket_name:
#             bucket_name = frappe.conf.get("aws_s3_bucket_name")
#         if not region:
#             region = frappe.conf.get("aws_default_region")
#         if not aws_access_key_id:
#             aws_access_key_id = frappe.conf.get("aws_key") or frappe.conf.get("s3_access_key")
#         if not aws_secret_access_key:
#             aws_secret_access_key = frappe.conf.get("aws_secret") or frappe.conf.get("s3_secret_key")
#
#         # Validate AWS configuration
#         missing_configs = []
#         if not bucket_name:
#             missing_configs.append("aws_s3_bucket or aws_s3_bucket_name")
#         if not region:
#             missing_configs.append("aws_region")
#         if not aws_access_key_id:
#             missing_configs.append("aws_access_key_id")
#         if not aws_secret_access_key:
#             missing_configs.append("aws_secret_access_key")
#
#         if missing_configs:
#             frappe.throw(f"Missing AWS configuration: {', '.join(missing_configs)}")
#
#         # Create S3 client
#         s3 = boto3.client(
#             "s3",
#             aws_access_key_id=aws_access_key_id,
#             aws_secret_access_key=aws_secret_access_key,
#             region_name=region,
#         )
#
#         # Construct S3 key
#         key = f"{folder.rstrip('/')}/{filename.lstrip('/')}"
#
#         # Generate presigned POST
#         presigned = s3.generate_presigned_post(
#             Bucket=bucket_name,
#             Key=key,
#             Fields={"Content-Type": file_type},
#             Conditions=[
#                 {"Content-Type": file_type},
#                 ["starts-with", "$Content-Type", ""]
#             ],
#             ExpiresIn=3600
#         )
#
#         # Construct file URL
#         file_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{key}"
#
#         return {"success": True, "data": presigned, "file_url": file_url}
#
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "Presigned URL Failed")
#         return {"success": False, "error": str(e)}
