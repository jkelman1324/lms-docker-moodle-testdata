#!/usr/bin/env python3

import os
import subprocess
import sys

import edq.util.pyimport

THIS_DIR = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
DATA_DIR = os.path.join(THIS_DIR, '..', 'lms-testdata', 'testdata')
LOAD_SCRIPT = os.path.join(THIS_DIR, '..', 'lms-testdata', 'load.py')

SERVER = 'http://127.0.0.1:4000'

USER_ATTRIBUTES = ["username", "firstname", "lastname", "email", "password"]
COURSE_ATTRIBUTES = ["shortname", "fullname", "idnumber", "category", "enrolment_1", "enrolment_2"]

ROLE_MAPPING = {
    "other": "student",  # HACK(JK): The "guest" role is preferred here, but Moodle is not allowing it.
    "student": "student",
    "grader": "teacher",
    "admin": "editingteacher",
    "owner": "manager",
}

EMPTY_NAME = "__EMPTY_NAME__"

def run(command, capture_output = False):
    result = subprocess.run(command, shell = True, check = True, capture_output = capture_output)

    if (not capture_output):
        return result

    return result.stdout.decode('utf-8').splitlines()

def run_sql(sql, **kwargs):
    path = "/tmp/sqlcommand"
    with open(path, "w") as file:
        file.write(sql)

    return run(f'mysql moodle < {path}', **kwargs)

def add_users(users):
    path = os.path.join(edq.util.dirent.get_temp_dir(), "users.csv")

    for user in users.values():
        keys = USER_ATTRIBUTES.copy()

        row = [
            user["short-name"],
            EMPTY_NAME,
            user["name"],
            user["email"],
            user["password"],
        ]

        for (i, (course_id, course_info)) in enumerate(user["course-info"].items()):
            keys.append(f"course{i + 1}")
            row.append(course_id)

            keys.append(f"role{i + 1}")
            row.append(ROLE_MAPPING[course_info["role"]])

        with open(path, "w") as file:
            file.write(",".join(keys) + "\n")
            file.write(",".join(row) + "\n")

        if (user["name"] != "server-owner"):
            run(f"php /var/www/html/admin/tool/uploaduser/cli/uploaduser.php --file={path} --mode=addnew")

        sql = f"""
            SELECT id
            FROM mdl_user
            WHERE username = '{user["name"]}'
            ;
        """
        output = run_sql(sql, capture_output = True)
        moodle_user_id = output[1]

        sql = f"""
            UPDATE mdl_user
            SET id = {user["id"]}
            WHERE id = {moodle_user_id}
            ;
        """
        run_sql(sql)

        tables = [
            'mdl_config_log',
            'mdl_files',
            'mdl_logstore_standard_log',
            'mdl_repository_instances',
            'mdl_user_preferences',
            'mdl_user_enrolments',
            'mdl_role_assignments',
        ]

        for table in tables:
            sql = f"""
                UPDATE {table}
                SET userid = {user["id"]}
                WHERE userid = {moodle_user_id}
                ;
            """
            run_sql(sql)


def add_courses(courses):
    path = os.path.join(edq.util.dirent.get_temp_dir(), "courses.csv")
    for course in courses.values():
        row = [
            course["short-name"],
            course["name"],
            course["id"],
            "1",
            "manual",
            "guest",
        ]

        with open(path, "w") as file:
            file.write(",".join(COURSE_ATTRIBUTES) + "\n")
            file.write(",".join(row) + "\n")

        result = run(f"php /var/www/html/admin/tool/uploadcourse/cli/uploadcourse.php --file={path} --mode=createnew", capture_output = True)

        moodle_course_id = None
        for line in result:
            if (str(course["id"]) in line):
                moodle_course_id = line.split("\t")[2]
                break

        if (moodle_course_id is None):
            raise ValueError("Course id not found.")

        sql = f"""
            UPDATE mdl_course
            SET id = {course["id"]}
            WHERE id = {moodle_course_id}
            ;
        """
        run_sql(sql)

        tables = [
            "mdl_enrol",
        ]

        for table in tables:
            sql = f"""
                UPDATE {table}
                SET courseid = {course["id"]}
                WHERE courseid = {moodle_course_id}
                ;
            """
            run_sql(sql)

def clean_up():
    sql = f"""
        DELETE FROM mdl_user_preferences;
    """
    run_sql(sql)

def main():
    dataset = edq.util.pyimport.import_path(LOAD_SCRIPT).load_test_data(DATA_DIR)
    (users, courses, assignments, groupsets, submissions) = dataset

    # HACK(JK): The server owner has hard-coded id in the code base.
    users["server-owner"]["id"] = 2

    # Add the courses.
    add_courses(courses)

    # Add the users.
    add_users(users)

    # Clean up.
    clean_up()

    return 0

if __name__ == '__main__':
    sys.exit(main())
