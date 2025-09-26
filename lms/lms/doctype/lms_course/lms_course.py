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
    """Return a structured course with profile, modules, and content"""
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
    for r in reviews:
        reviewer_name = frappe.get_value("User Profile", {"user": r.owner}, "parent_full_name")
        reviews_list.append(
            {
                "id": r.name,
                "reviewer_name": reviewer_name,
                "rating": r.rating,
                "comment": r.review,
                "date": r.creation,
            }
        )

    # Modules & Content
    modules_list = []
    for module_content in course.module_content:
        content = frappe.get_doc("LMS Course Module Content", module_content.name).as_dict()

        quiz_questions = []
        if content.get("content_type") == "Quiz":
            quiz_questions = frappe.get_all(
                "LMS Quiz Question",
                filters={"parent": content["name"], "parenttype": "LMS Course Module Content"},
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

        modules_list.append(
            {
                "id": content.get("name"),
                "module_name": content.get("module_name"),
                "content_type": content.get("content_type"),
                "essay": {"title": content.get("essay_title"), "content": content.get("essay_content")}
                if content.get("content_type") == "Essay"
                else None,
                "video": {
                    "title": content.get("video_title"),
                    "description": content.get("video_description"),
                    "url": content.get("video_content"),
                }
                if content.get("content_type") == "Video"
                else None,
                "quiz": {
                    "title": content.get("quiz_title"),
                    "description": content.get("quiz_description"),
                    "questions": quiz_questions,
                }
                if content.get("content_type") == "Quiz"
                else None,
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
        "education_level": course.education_level,
        "subject": course.subject,
        "price": course.course_price,
        "currency": course.currency,
        "rating": course.rating,
        "enrollments": course.enrollments,
        "instructors": instructor_profiles,
        "reviews": reviews_list,
        "modules": modules_list,
    }


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
    and Quiz Questions using direct SQL.
    """
    import json
    from frappe.utils import now, generate_hash

    try:
        data = {}
        if frappe.request and frappe.request.data:
            data = json.loads(frappe.request.data)

        # Generate course name
        course_name = generate_hash(length=10)
        creation_time = now()
        owner = frappe.session.user

        # === Create Course using SQL ===
        course_fields = {
            "name": course_name,
            "title": data.get("title", ""),
            "tags": data.get("tags", ""),
            "status": data.get("status", "Draft"),
            "image": data.get("image", ""),
            "published": data.get("published", 0),
            "published_on": data.get("published_on"),
            "upcoming": data.get("upcoming", 0),
            "featured": data.get("featured", 0),
            "disable_self_learning": data.get("disable_self_learning", 0),
            "short_introduction": data.get("short_introduction", ""),
            "description": data.get("description", ""),
            "paid_course": data.get("paid_course", 0),
            "enable_certification": data.get("enable_certification", 0),
            "paid_certificate": data.get("paid_certificate", 0),
            "course_price": data.get("course_price", 0),
            "currency": data.get("currency", ""),
            "amount_usd": data.get("amount_usd", 0),
            "enrollments": data.get("enrollments", 0),
            "lessons": data.get("lessons", 0),
            "rating": data.get("rating", 0),
            "course_language": data.get("course_language", ""),
            "requirement": data.get("requirement", ""),
            "education_level": data.get("education_level", ""),
            "subject": data.get("subject", ""),
            "draft": data.get("draft", 1),
            "creation": creation_time,
            "modified": creation_time,
            "modified_by": owner,
            "owner": owner,
            "docstatus": 0
        }

        # Insert course
        frappe.db.sql("""
            INSERT INTO `tabLMS Course` 
            (name, title, tags, status, image, published, published_on, upcoming, featured, 
             disable_self_learning, short_introduction, description, paid_course, 
             enable_certification, paid_certificate, course_price, currency, amount_usd,
             enrollments, lessons, rating, course_language, requirement, education_level,
             subject, draft, creation, modified, modified_by, owner, docstatus)
            VALUES 
            (%(name)s, %(title)s, %(tags)s, %(status)s, %(image)s, %(published)s, %(published_on)s,
             %(upcoming)s, %(featured)s, %(disable_self_learning)s, %(short_introduction)s, 
             %(description)s, %(paid_course)s, %(enable_certification)s, %(paid_certificate)s,
             %(course_price)s, %(currency)s, %(amount_usd)s, %(enrollments)s, %(lessons)s,
             %(rating)s, %(course_language)s, %(requirement)s, %(education_level)s, %(subject)s,
             %(draft)s, %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, %(docstatus)s)
        """, course_fields)

        # === Add Instructors using SQL ===
        instructor_names = []
        if "instructors" in data:
            for idx, inst in enumerate(data["instructors"]):
                instructor_name = generate_hash(length=10)
                instructor_names.append(instructor_name)
                
                frappe.db.sql("""
                    INSERT INTO `tabCourse Instructor`
                    (name, instructor, parent, parenttype, parentfield, idx, creation, modified, 
                     modified_by, owner, docstatus)
                    VALUES 
                    (%(name)s, %(instructor)s, %(parent)s, 'LMS Course', 'instructors', %(idx)s,
                     %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
                """, {
                    "name": instructor_name,
                    "instructor": inst.get("instructor"),
                    "parent": course_name,
                    "idx": idx + 1,
                    "creation": creation_time,
                    "modified": creation_time,
                    "modified_by": owner,
                    "owner": owner
                })

        # === Add Content using SQL ===
        content_names = []
        quiz_questions_created = []

        if "content" in data:
            for idx, content_item in enumerate(data["content"]):
                content_name = generate_hash(length=10)
                content_names.append(content_name)

                frappe.db.sql("""
                    INSERT INTO `tabLMS Course Module Content`
                    (name, module_name, content_type, essay_title, essay_content, video_title,
                     video_description, video_content, quiz_title, quiz_description, parent,
                     parenttype, parentfield, idx, creation, modified, modified_by, owner, docstatus)
                    VALUES
                    (%(name)s, %(module_name)s, %(content_type)s, %(essay_title)s, %(essay_content)s,
                     %(video_title)s, %(video_description)s, %(video_content)s, %(quiz_title)s,
                     %(quiz_description)s, %(parent)s, 'LMS Course', 'module_content', %(idx)s,
                     %(creation)s, %(modified)s, %(modified_by)s, %(owner)s, 0)
                """, {
                    "name": content_name,
                    "module_name": content_item.get("module_name", ""),
                    "content_type": content_item.get("content_type", ""),
                    "essay_title": content_item.get("essay_title", ""),
                    "essay_content": content_item.get("essay_content", ""),
                    "video_title": content_item.get("video_title", ""),
                    "video_description": content_item.get("video_description", ""),
                    "video_content": content_item.get("video_content", ""),
                    "quiz_title": content_item.get("quiz_title", ""),
                    "quiz_description": content_item.get("quiz_description", ""),
                    "parent": course_name,
                    "idx": idx + 1,
                    "creation": creation_time,
                    "modified": creation_time,
                    "modified_by": owner,
                    "owner": owner
                })

                # === Add Quiz Questions using SQL ===
                if (content_item.get("content_type") == "Quiz" and 
                    content_item.get("quiz_questions")):
                    
                    for q_idx, q in enumerate(content_item.get("quiz_questions", [])):
                        question_name = generate_hash(length=10)
                        
                        frappe.db.sql("""
                            INSERT INTO `tabLMS Quiz Question`
                            (name, question, question_type, option_a, option_b, option_c, option_d,
                             correct_answer, marks, points, is_required, explanation, parent,
                             parenttype, parentfield, idx, creation, modified, modified_by, owner, docstatus)
                            VALUES
                            (%(name)s, %(question)s, %(question_type)s, %(option_a)s, %(option_b)s,
                             %(option_c)s, %(option_d)s, %(correct_answer)s, %(marks)s, %(points)s,
                             %(is_required)s, %(explanation)s, %(parent)s, 'LMS Course Module Content',
                             'quiz_questions', %(idx)s, %(creation)s, %(modified)s, %(modified_by)s,
                             %(owner)s, 0)
                        """, {
                            "name": question_name,
                            "question": q.get("question", ""),
                            "question_type": q.get("question_type", "Multiple Choice"),
                            "option_a": q.get("option_a", ""),
                            "option_b": q.get("option_b", ""),
                            "option_c": q.get("option_c", ""),
                            "option_d": q.get("option_d", ""),
                            "correct_answer": q.get("correct_answer", ""),
                            "marks": q.get("marks", 1),
                            "points": q.get("points", 1),
                            "is_required": q.get("is_required", 0),
                            "explanation": q.get("explanation", ""),
                            "parent": content_name,
                            "idx": q_idx + 1,
                            "creation": creation_time,
                            "modified": creation_time,
                            "modified_by": owner,
                            "owner": owner
                        })
                        
                        quiz_questions_created.append({
                            "name": question_name,
                            "question": q.get("question", ""),
                            "parent_content": content_name,
                            "module_name": content_item.get("module_name", "")
                        })

        # Commit all changes
        frappe.db.commit()

        # === Prepare response using SQL ===
        module_content_summary = []
        
        # Get module content with quiz question counts
        content_data = frappe.db.sql("""
            SELECT 
                mc.name,
                mc.module_name,
                mc.content_type,
                COUNT(qq.name) as quiz_questions_count
            FROM `tabLMS Course Module Content` mc
            LEFT JOIN `tabLMS Quiz Question` qq ON qq.parent = mc.name
            WHERE mc.parent = %(course_name)s
            GROUP BY mc.name, mc.module_name, mc.content_type
            ORDER BY mc.idx
        """, {"course_name": course_name}, as_dict=True)

        module_content_summary = list(content_data)

        return {
            "success": True,
            "message": "Course created successfully",
            "course_name": course_name,
            "module_content": module_content_summary,
            "quiz_questions_created": quiz_questions_created,
            "total_quiz_questions": len(quiz_questions_created)
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Create Course Failed")
        return {"error": str(e), "traceback": frappe.get_traceback()}

@frappe.whitelist()
def create_course_direct():
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

        # === Add Content First ===
        content_rows = {}  # Store content row references

        if "content" in data:
            for idx, content_item in enumerate(data["content"]):
                # Create the module content row without quiz questions first
                content_row = course_doc.append(
                    "module_content",
                    {
                        "module_name": content_item.get("module_name"),
                        "content_type": content_item.get("content_type"),
                        "essay_title": content_item.get("essay_title"),
                        "essay_content": content_item.get("essay_content"),
                        "video_title": content_item.get("video_title"),
                        "video_description": content_item.get("video_description"),
                        "video_content": content_item.get("video_content"),
                        "quiz_title": content_item.get("quiz_title"),
                        "quiz_description": content_item.get("quiz_description"),
                    },
                )

                # Store reference to this content row for later quiz question assignment
                content_rows[idx] = {
                    "row": content_row,
                    "quiz_questions": content_item.get("quiz_questions", [])
                    if content_item.get("content_type") == "Quiz"
                    else [],
                }

            # Save to get the content rows created with proper names
            course_doc.save(ignore_permissions=True)

            # === Now Add Quiz Questions to each content row ===
            quiz_questions_created = []

            for idx, content_info in content_rows.items():
                if content_info["quiz_questions"]:
                    # Get the saved content row
                    content_row = course_doc.module_content[idx]

                    for q in content_info["quiz_questions"]:
                        # Create quiz question document separately
                        quiz_question = frappe.new_doc("LMS Quiz Question")
                        quiz_question.update(
                            {
                                "parenttype": "LMS Course Module Content",
                                "parentfield": "quiz_questions",
                                "parent": content_row.name,
                                "question": q.get("question"),
                                "question_type": q.get("question_type"),
                                "option_a": q.get("option_a"),
                                "option_b": q.get("option_b"),
                                "option_c": q.get("option_c"),
                                "option_d": q.get("option_d"),
                                "correct_answer": q.get("correct_answer"),
                                "marks": q.get("marks", 1),
                                "points": q.get("points", 1),
                                "is_required": q.get("is_required", 0),
                                "explanation": q.get("explanation"),
                            }
                        )

                        quiz_question.insert(ignore_permissions=True)
                        quiz_questions_created.append(
                            {
                                "name": quiz_question.name,
                                "question": quiz_question.question,
                                "parent_content": content_row.name,
                                "module_name": content_row.module_name,
                            }
                        )

        frappe.db.commit()

        # Reload the course document to get updated child tables
        course_doc.reload()

        # Prepare response
        module_content_summary = []
        for row in course_doc.module_content:
            # Count quiz questions for this content
            # quiz_count = frappe.db.count("LMS Quiz Question", {
            #     "parent": row.name,
            #     "parenttype": "LMS Course Module Content"
            # })
            try:
                quiz_count = frappe.db.count("LMS Quiz Question", {
                    "parent": row.name,
                    "parenttype": "LMS Course Module Content"
                })
            except Exception as e:
                print(f"Quiz count query failed: {e}")
                quiz_count = 0

            module_content_summary.append(
                {
                    "name": row.name,
                    "module_name": row.module_name,
                    "content_type": row.content_type,
                    "quiz_questions_count": quiz_count,
                }
            )

        return {
            "success": True,
            "message": "Course created successfully",
            "course_name": course_doc.name,
            "module_content": module_content_summary,
            "quiz_questions_created": quiz_questions_created,
            "total_quiz_questions": len(quiz_questions_created),
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Create Course Failed")
        return {"error": str(e), "traceback": frappe.get_traceback()}


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
        order_by="creation desc",
    )

    courses = [serialize_course(c["name"]) for c in course_names]

    return paginated_response(courses, page, total_pages, total_courses)


# Get Tutor Enrolled Courses and Count
@frappe.whitelist()
def get_tutor_courses_with_enrollments(tutor, course_name=None, status=None):
    """
    Get all courses where the tutor is an instructor and at least one student is enrolled.
    Optionally filter by course_name and status.
    """
    # Step 1: Get all course names where tutor is instructor
    course_names = frappe.get_all("Course Instructor", filters={"instructor": tutor}, pluck="parent")

    # Step 2: Filter by course_name and status if provided
    course_filters = {}
    if course_name:
        course_filters["name"] = course_name
    if status:
        course_filters["status"] = status

    if course_filters:
        filtered_courses = frappe.get_all("LMS Course", filters=course_filters, fields=["name"])
        filtered_course_names = set(c["name"] for c in filtered_courses)
        course_names = [name for name in course_names if name in filtered_course_names]

    courses = []
    for cname in course_names:
        # Get enrolled students for this course
        students = frappe.get_all(
            "LMS Enrollment", filters={"course": cname, "member_type": "Student"}, fields=["member"]
        )
        if students:
            enriched_students = []
            for s in students:
                user_profile = frappe.get_value("User Profile", {"user": s["member"]}, "*", as_dict=True)
                enriched_students.append(user_profile if user_profile else s)
            course_info = serialize_course(cname)
            course_info["enrolled_students"] = enriched_students
            courses.append(course_info)

    return {"success": True, "data": courses, "count": len(courses)}
