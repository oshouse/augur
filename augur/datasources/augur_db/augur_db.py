#SPDX-License-Identifier: MIT
"""
Data source that uses the Augur relational database of GitHub activity.
"""

import pandas as pd
import sqlalchemy as s
import numpy as np
import re
import datetime
from augur import logger
from augur.util import annotate
import base64

class Augur(object):
    """Uses the Augur database to return dataframes with interesting GitHub indicators"""

    def __init__(self, user, password, host, port, dbname, schema, projects=None):
        """
        Connect to Augur

        :param dbstr: The [database string](http://docs.sqlalchemy.org/en/latest/core/engines.html) to connect to the Augur database
        """
        self.DB_STR = 'postgresql://{}:{}@{}:{}/{}'.format(
            user, password, host, port, dbname
        )

        self.db = s.create_engine(self.DB_STR, poolclass=s.pool.NullPool,
            connect_args={'options': '-csearch_path={}'.format(schema)})

        logger.debug('Augur DB: Connecting to {} schema of {}:{}/{} as {}'.format(schema, host, port, dbname, user))

        self.projects = projects
        # try:
        #     self.userid('howderek')
        # except Exception as e:
        #     logger.error("Could not connect to GHTorrent database. Error: " + str(e))

    #####################################
    ###           EVOLUTION           ###
    #####################################

    @annotate(tag='code-changes')
    def code_changes(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Returns a timeseries of the count of code commits.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of commits/period
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        code_changes_SQL = ''

        if not repo_id:
            code_changes_SQL = s.sql.text("""
                SELECT
                    commits.repo_id,
                    repo_name,
                    date_trunc(:period, cmt_committer_date::DATE) as date,
                    COUNT(cmt_commit_hash) as commit_count
                FROM commits JOIN repo ON repo.repo_id = commits.repo_id
                WHERE commits.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND cmt_committer_date BETWEEN :begin_date AND :end_date
                GROUP BY commits.repo_id, date, repo_name
                ORDER BY commits.repo_id, date
            """)

            results = pd.read_sql(code_changes_SQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                     'begin_date': begin_date, 'end_date': end_date})
            return results

        else:
            code_changes_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    date_trunc(:period, cmt_committer_date::DATE) as date,
                    COUNT(cmt_commit_hash) as commit_count
                FROM commits JOIN repo ON commits.repo_id = repo.repo_id
                WHERE commits.repo_id = :repo_id
                AND cmt_committer_date BETWEEN :begin_date AND :end_date
                GROUP BY date, repo_name
                ORDER BY date
            """)

            results = pd.read_sql(code_changes_SQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                     'begin_date': begin_date, 'end_date': end_date})
            return results


    @annotate(tag='pull-requests-merge-contributor-new')
    def pull_requests_merge_contributor_new(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Returns a timeseries of the count of persons contributing with an accepted commit for the first time.

        :param repo_id: The repository's id
        :param repo_group_id: The repository's group id
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of persons/period
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if repo_id:
            commitNewContributor = s.sql.text("""
                SELECT date_trunc(:period, new_date::DATE) as commit_date,
                COUNT(cmt_author_email), repo_name
                FROM ( SELECT repo_name, cmt_author_email, MIN(TO_TIMESTAMP(cmt_author_date,'YYYY-MM-DD')) AS new_date
                FROM commits JOIN repo ON commits.repo_id = repo.repo_id
                WHERE commits.repo_id = :repo_id
                AND TO_TIMESTAMP(cmt_author_date,'YYYY-MM-DD') BETWEEN :begin_date AND :end_date AND cmt_author_email IS NOT NULL
                GROUP BY cmt_author_email, repo_name
                ) as abc GROUP BY commit_date, repo_name
            """)
            results = pd.read_sql(commitNewContributor, self.db, params={'repo_id': repo_id, 'period': period,
                                                                         'begin_date': begin_date,
                                                                         'end_date': end_date})
        else:
            commitNewContributor = s.sql.text("""
                SELECT abc.repo_id, repo_name ,date_trunc(:period, new_date::DATE) as commit_date,
                    COUNT(cmt_author_email)
                FROM (SELECT cmt_author_email, MIN(TO_TIMESTAMP(cmt_author_date, 'YYYY-MM-DD')) AS new_date, repo_id
                    FROM commits
                    WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                        AND TO_TIMESTAMP(cmt_author_date, 'YYYY-MM-DD') BETWEEN :begin_date AND :end_date
                        AND cmt_author_email IS NOT NULL
                    GROUP BY cmt_author_email, repo_id
                    ) as abc, repo
                WHERE abc.repo_id = repo.repo_id
                GROUP BY abc.repo_id, repo_name, commit_date
            """)
            results = pd.read_sql(commitNewContributor, self.db,
                                  params={'repo_group_id': repo_group_id, 'period': period,
                                          'begin_date': begin_date,
                                          'end_date': end_date})
        return results

    @annotate(tag='issues-first-time-opened')
    def issues_first_time_opened(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Returns a timeseries of the count of persons opening an issue for the first time.

        :param repo_id: The repository's id
        :param repo_group_id: The repository's group id
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of persons/period
        """

        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if repo_id:
            issueNewContributor = s.sql.text("""
                SELECT
                    date_trunc(:period, new_date::DATE) as issue_date,
                    COUNT(gh_user_id),
                    repo_name
                FROM (
                    SELECT
                        gh_user_id,
                        MIN(issues.created_at) AS new_date,
                        repo_name
                    FROM
                        issues JOIN repo ON issues.repo_id = repo.repo_id
                    WHERE
                        issues.repo_id = :repo_id
                        AND issues.created_at BETWEEN :begin_date AND :end_date
                    GROUP BY gh_user_id, repo_name
                ) as abc
                GROUP BY issue_date, repo_name
                ORDER BY issue_date
            """)
            results = pd.read_sql(issueNewContributor, self.db, params={'repo_id': repo_id, 'period': period,
                                                                        'begin_date': begin_date, 'end_date': end_date})
        else:
            issueNewContributor = s.sql.text("""
                SELECT
                    repo.repo_id,
                    repo_name,
                    date_trunc(:period, new_date::DATE) as issue_date,
                    COUNT(gh_user_id)
                FROM (
                    SELECT
                        repo_id,
                        gh_user_id,
                        MIN(created_at) AS new_date
                    FROM
                        issues
                    WHERE
                        repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                        AND created_at BETWEEN :begin_date AND :end_date
                    GROUP BY gh_user_id, repo_id
                ) as abc, repo
                WHERE repo.repo_id= abc.repo_id
                GROUP BY repo.repo_id, issue_date
                ORDER BY issue_date
            """)
            results = pd.read_sql(issueNewContributor, self.db,
                                  params={'repo_group_id': repo_group_id, 'period': period,
                                          'begin_date': begin_date, 'end_date': end_date})
        return results

    @annotate(tag='issues-first-time-closed')
    def issues_first_time_closed(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None, ):
        """
        Returns a timeseries of the count of persons closing an issue for the first time.

        :param repo_id: The repository's id
        :param repo_group_id: The repository's group id
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of persons/period
        """

        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if repo_id:
            issuesClosedSQL = s.sql.text("""
                SELECT date_trunc(:period, new_date::DATE) AS issue_date,
                    COUNT(cntrb_id),
                    repo_name
                FROM (
                        SELECT issue_events.cntrb_id, MIN(issue_events.created_at) AS new_date, repo_name
                        FROM issue_events,
                            repo,
                            issues
                        WHERE repo.repo_id = :repo_id
                        AND action = 'closed'
                        AND repo.repo_id = issues.repo_id
                        AND issues.issue_id = issue_events.issue_id
                        And issue_events.created_at BETWEEN :begin_date AND :end_date
                        GROUP BY issue_events.cntrb_id, repo_name
                    ) AS iss_close
                GROUP BY issue_date, repo_name
            """)
            results = pd.read_sql(issuesClosedSQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                    'begin_date': begin_date, 'end_date': end_date})
        else:
            issuesClosedSQL = s.sql.text("""
                 SELECT date_trunc(:period, new_date::DATE) AS issue_date,
                    COUNT(cntrb_id),
                    repo_name, repo_id
                FROM (
                        SELECT issue_events.cntrb_id, MIN(issue_events.created_at) AS new_date, repo_name, repo.repo_id
                        FROM issue_events,
                            repo,
                            issues
                        WHERE repo.repo_group_id = :repo_group_id
                        AND action = 'closed'
                        AND repo.repo_id = issues.repo_id
                        AND issues.issue_id = issue_events.issue_id
                        And issue_events.created_at BETWEEN :begin_date AND :end_date
                        GROUP BY issue_events.cntrb_id, repo.repo_id, repo_name
                    ) AS iss_close
                GROUP BY repo_id, repo_name,issue_date
            """)
            results = pd.read_sql(issuesClosedSQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                    'begin_date': begin_date, 'end_date': end_date})

        return results

    @annotate(tag='sub-projects')
    def sub_projects(self, repo_group_id, repo_id=None, begin_date=None, end_date=None):
        """
        Returns number of sub-projects
        :param repo_id: The repository's id
        :param repo_group_id: The repository's group id
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if repo_id:
            sub_projectsSQL = s.sql.text("""
                SELECT COUNT(*)  AS sub_project_count
                FROM repo
                WHERE repo_group_id = (
                SELECT repo_group_id
                FROM repo
                WHERE  repo_id = :repo_id)
                AND repo_added BETWEEN :begin_date AND :end_date
            """)

            results = pd.read_sql(sub_projectsSQL, self.db, params={'repo_id': repo_id,
                                                                    'begin_date': begin_date, 'end_date': end_date})
        else:
            sub_projectsSQL = s.sql.text("""
                SELECT COUNT(*) AS sub_project_count
                FROM repo
                WHERE repo_group_id = :repo_group_id
                AND repo_added BETWEEN :begin_date AND :end_date
            """)

            results = pd.read_sql(sub_projectsSQL, self.db, params={'repo_group_id': repo_group_id,
                                                                    'begin_date': begin_date, 'end_date': end_date})
        return results

    @annotate(tag='contributors')
    def contributors(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Returns a timeseries of all the contributions to a project.

        DataFrame has these columns:
        date
        commits
        pull_requests
        issues
        commit_comments
        pull_request_comments
        issue_comments
        total

        :param repo_id: The repository's id
        :param repo_group_id: The repository's group id
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of persons/period
        """

        # In this version, pull request, pr request comments,issue comments haven't be calculated
        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if repo_id:
            contributorsSQL = s.sql.text("""
               SELECT id                           AS user_id,
                    SUM(commits)                 AS commits,
                    SUM(issues)                  AS issues,
                    SUM(commit_comments)         AS commit_comments,
                    SUM(issue_comments)          AS issue_comments,
                    SUM(pull_requests)           AS pull_requests,
                    SUM(pull_request_comments)   AS pull_request_comments,
                    SUM(a.commits + a.issues + a.commit_comments + a.issue_comments + a.pull_requests +
                        a.pull_request_comments) AS total,
                    a.repo_id, repo.repo_name
                FROM (
                        (SELECT gh_user_id AS id,
                                0          AS commits,
                                COUNT(*)   AS issues,
                                0          AS commit_comments,
                                0          AS issue_comments,
                                0          AS pull_requests,
                                0          AS pull_request_comments,
                                repo_id
                        FROM issues
                        WHERE repo_id = :repo_id
                            AND created_at BETWEEN :begin_date AND :end_date
                            AND gh_user_id IS NOT NULL
                        GROUP BY gh_user_id, repo_id)
                        UNION ALL
                        (SELECT cmt_ght_author_id AS id,
                                COUNT(*)          AS commits,
                                0                 AS issues,
                                0                 AS commit_comments,
                                0                 AS issue_comments,
                                0                 AS pull_requests,
                                0                 AS pull_request_comments,
                                repo_id
                        FROM commits
                        WHERE repo_id = :repo_id
                            AND cmt_ght_author_id IS NOT NULL
                            AND cmt_committer_date BETWEEN :begin_date AND :end_date
                        GROUP BY cmt_ght_author_id, repo_id)
                        UNION ALL
                        (SELECT cntrb_id AS id,
                                0        AS commits,
                                0        AS issues,
                                COUNT(*) AS commit_comments,
                                0        AS issue_comments,
                                0        AS pull_requests,
                                0        AS pull_request_comments,
                                repo_id
                        FROM commit_comment_ref,
                            commits,
                            message
                        WHERE commit_comment_ref.cmt_id = commit_comment_ref.cmt_id
                            AND message.msg_id = commit_comment_ref.msg_id
                            AND repo_id = :repo_id
                            AND created_at BETWEEN :begin_date AND :end_date
                        GROUP BY id, repo_id)
                        UNION ALL
                        (
                            SELECT message.cntrb_id AS id,
                                    0                AS commits,
                                    0                AS issues,
                                    0                AS commit_comments,
                                    count(*)         AS issue_comments,
                                    0                AS pull_requests,
                                    0                AS pull_request_comments,
                                repo_id
                            FROM issues,
                                issue_message_ref,
                                message
                            WHERE repo_id = :repo_id
                            AND gh_user_id IS NOT NULL
                            AND issues.issue_id = issue_message_ref.issue_id
                            AND issue_message_ref.msg_id = message.msg_id
                            AND created_at BETWEEN :begin_date AND :end_date
                            GROUP BY id, repo_id
                        )
                    ) a, repo
                WHERE a.repo_id = repo.repo_id
                GROUP BY a.id, a.repo_id, repo_name
                ORDER BY total DESC
            """)

            results = pd.read_sql(contributorsSQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                    'begin_date': begin_date, 'end_date': end_date})
        else:
            contributorsSQL = s.sql.text("""
               SELECT id                           AS user_id,
                    SUM(commits)                 AS commits,
                    SUM(issues)                  AS issues,
                    SUM(commit_comments)         AS commit_comments,
                    SUM(issue_comments)          AS issue_comments,
                    SUM(pull_requests)           AS pull_requests,
                    SUM(pull_request_comments)   AS pull_request_comments,
                    SUM(a.commits + a.issues + a.commit_comments + a.issue_comments + a.pull_requests +
                        a.pull_request_comments) AS total, a.repo_id, repo_name
                FROM (
                        (SELECT gh_user_id AS id,
                                repo_id,
                                0          AS commits,
                                COUNT(*)   AS issues,
                                0          AS commit_comments,
                                0          AS issue_comments,
                                0          AS pull_requests,
                                0          AS pull_request_comments
                        FROM issues
                        WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                            AND created_at BETWEEN :begin_date AND :end_date
                            AND gh_user_id IS NOT NULL
                        GROUP BY gh_user_id, repo_id)
                        UNION ALL
                        (SELECT cmt_ght_author_id AS id,
                                repo_id,
                                COUNT(*)          AS commits,
                                0                 AS issues,
                                0                 AS commit_comments,
                                0                 AS issue_comments,
                                0                 AS pull_requests,
                                0                 AS pull_request_comments
                        FROM commits
                        WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                            AND cmt_ght_author_id IS NOT NULL
                            AND cmt_committer_date BETWEEN :begin_date AND :end_date
                        GROUP BY cmt_ght_author_id, repo_id)
                        UNION ALL
                        (SELECT cntrb_id AS id,
                                repo_id,
                                0        AS commits,
                                0        AS issues,
                                COUNT(*) AS commit_comments,
                                0        AS issue_comments,
                                0        AS pull_requests,
                                0        AS pull_request_comments
                        FROM commit_comment_ref,
                            commits,
                            message
                        WHERE commit_comment_ref.cmt_id = commit_comment_ref.cmt_id
                            AND message.msg_id = commit_comment_ref.msg_id
                            AND repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                            AND created_at BETWEEN :begin_date AND :end_date
                        GROUP BY id, repo_id)
                        UNION ALL
                        (
                            SELECT message.cntrb_id AS id,
                                    repo_id,
                                    0                AS commits,
                                    0                AS issues,
                                    0                AS commit_comments,
                                    count(*)         AS issue_comments,
                                    0                AS pull_requests,
                                    0                AS pull_request_comments
                            FROM issues,
                                issue_message_ref,
                                message
                            WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                            AND gh_user_id IS NOT NULL
                            AND issues.issue_id = issue_message_ref.issue_id
                            AND issue_message_ref.msg_id = message.msg_id
                            AND created_at BETWEEN :begin_date AND :end_date
                            GROUP BY id, repo_id
                        )
                    ) a, repo
                WHERE a.repo_id = repo.repo_id
                GROUP BY a.id, a.repo_id, repo_name
                ORDER BY total DESC
            """)

            results = pd.read_sql(contributorsSQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                    'begin_date': begin_date, 'end_date': end_date})
        return results

    @annotate(tag='contributors-new')
    def contributors_new(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Returns a timeseries of new contributions to a project.

        :param repo_id: The repository's id
        :param repo_group_id: The repository's group id
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of persons/period
        """

        # In this version, pull request, pr request comments,issue comments haven't be calculated
        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if repo_id:
            contributorsNewSQL = s.sql.text("""
                SELECT date_trunc(:period, b.created_at::DATE) AS contribute_at, COUNT(id) AS count, repo.repo_id, repo_name
                FROM (
                        SELECT id as id, MIN(created_at) AS created_at, a.repo_id
                        FROM (
                                (SELECT gh_user_id AS id, MIN(created_at) AS created_at, repo_id
                                FROM issues
                                WHERE repo_id = :repo_id
                                    AND created_at BETWEEN :begin_date AND :end_date
                                    AND gh_user_id IS NOT NULL
                                GROUP BY gh_user_id, repo_id)
                                UNION ALL
                                (SELECT cmt_ght_author_id                                AS id,
                                        MIN(TO_TIMESTAMP(cmt_author_date, 'YYYY-MM-DD')) AS created_at,
                                        repo_id
                                FROM commits
                                WHERE repo_id = :repo_id
                                    AND cmt_ght_author_id IS NOT NULL
                                    AND TO_TIMESTAMP(cmt_author_date, 'YYYY-MM-DD') BETWEEN :begin_date AND :end_date
                                GROUP BY cmt_ght_author_id, repo_id)
                                UNION ALL
                                (SELECT cntrb_id as id, MIN(created_at) AS created_at, commits.repo_id
                                FROM commit_comment_ref,
                                        commits,
                                        message
                                where commits.cmt_id = commit_comment_ref.cmt_id
                                    and commits.repo_id = :repo_id
                                    and commit_comment_ref.msg_id = message.msg_id
                                group by id, commits.repo_id)
                                UNION ALL
                                (SELECT issue_events.cntrb_id AS id, MIN(issue_events.created_at) AS created_at, repo_id
                                FROM issue_events, issues
                                WHERE issues.repo_id = :repo_id
                                    AND issues.issue_id = issue_events.issue_id
                                    AND issue_events.created_at BETWEEN :begin_date AND :end_date
                                    AND issue_events.cntrb_id IS NOT NULL
                                    AND action = 'closed'
                                GROUP BY issue_events.cntrb_id, repo_id)
                            ) a
                        GROUP BY a.id, a.repo_id) b, repo
                WHERE repo.repo_id = b.repo_id
                GROUP BY contribute_at, repo.repo_id, repo_name
                """)

            results = pd.read_sql(contributorsNewSQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                       'begin_date': begin_date, 'end_date': end_date})
        else:
            contributorsNewSQL = s.sql.text("""
                SELECT date_trunc(:period, b.created_at::DATE) AS contribute_at, COUNT(id) AS count, repo.repo_id, repo_name
                FROM (
                        SELECT id as id, MIN(created_at) AS created_at, a.repo_id
                        FROM (
                                (SELECT gh_user_id AS id, MIN(created_at) AS created_at, repo_id
                                FROM issues
                                WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                                    AND created_at BETWEEN :begin_date AND :end_date
                                    AND gh_user_id IS NOT NULL
                                GROUP BY gh_user_id, repo_id)
                                UNION ALL
                                (SELECT cmt_ght_author_id                                AS id,
                                        MIN(TO_TIMESTAMP(cmt_author_date, 'YYYY-MM-DD')) AS created_at,
                                        repo_id
                                FROM commits
                                WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                                    AND cmt_ght_author_id IS NOT NULL
                                    AND TO_TIMESTAMP(cmt_author_date, 'YYYY-MM-DD') BETWEEN :begin_date AND :end_date
                                GROUP BY cmt_ght_author_id, repo_id)
                                UNION ALL
                                (SELECT cntrb_id as id, MIN(created_at) AS created_at, commits.repo_id
                                FROM commit_comment_ref,
                                        commits,
                                        message
                                where commits.cmt_id = commit_comment_ref.cmt_id
                                    and commits.repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                                    and commit_comment_ref.msg_id = message.msg_id
                                group by id, commits.repo_id)
                                UNION ALL
                                (SELECT issue_events.cntrb_id AS id, MIN(issue_events.created_at) AS created_at, repo_id
                                FROM issue_events, issues
                                WHERE issues.repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                                    AND issues.issue_id = issue_events.issue_id
                                    AND issue_events.created_at BETWEEN :begin_date AND :end_date
                                    AND issue_events.cntrb_id IS NOT NULL
                                    AND action = 'closed'
                                GROUP BY issue_events.cntrb_id, repo_id)
                            ) a
                        GROUP BY a.id, a.repo_id) b, repo
                WHERE repo.repo_id = b.repo_id
                GROUP BY contribute_at, repo.repo_id, repo_name
                """)

            results = pd.read_sql(contributorsNewSQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                       'begin_date': begin_date, 'end_date': end_date})
        return results

    @annotate(tag='code-changes-lines')
    def code_changes_lines(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """Returns a timeseries of code changes added and removed.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of code changes added and removed/period
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        code_changes_lines_SQL = ''

        if not repo_id:
            code_changes_lines_SQL = s.sql.text("""
                SELECT
                    commits.repo_id,
                    repo_name,
                    date_trunc(:period, cmt_author_date::DATE) as date,
                    SUM(cmt_added) as added,
                    SUM(cmt_removed) as removed
                FROM commits JOIN repo ON commits.repo_id = repo.repo_id
                WHERE commits.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND cmt_author_date BETWEEN :begin_date AND :end_date
                GROUP BY commits.repo_id, date, repo_name
                ORDER BY commits.repo_id, date
            """)

            results = pd.read_sql(code_changes_lines_SQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                           'begin_date': begin_date, 'end_date': end_date})

            return results

        else:
            code_changes_lines_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    date_trunc(:period, cmt_author_date::DATE) as date,
                    SUM(cmt_added) AS added,
                    SUM(cmt_removed) as removed
                FROM commits JOIN repo ON commits.repo_id = repo.repo_id
                WHERE commits.repo_id = :repo_id
                AND cmt_author_date BETWEEN :begin_date AND :end_date
                GROUP BY date, repo_name
                ORDER BY date;
            """)

            results = pd.read_sql(code_changes_lines_SQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                           'begin_date': begin_date, 'end_date': end_date})
            return results

    @annotate(tag='issues-new')
    def issues_new(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """Returns a timeseries of new issues opened.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of new issues/period
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        issues_new_SQL = ''

        if not repo_id:
            issues_new_SQL = s.sql.text("""
                SELECT
                    issues.repo_id,
                    repo_name,
                    date_trunc(:period, issues.created_at::DATE) as date,
                    COUNT(issue_id) as issues
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND issues.created_at BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS') AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY issues.repo_id, date, repo_name
                ORDER BY issues.repo_id, date
            """)

            results = pd.read_sql(issues_new_SQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                   'begin_date': begin_date, 'end_date': end_date})

            return results

        else:
            issues_new_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    date_trunc(:period, issues.created_at::DATE) as date,
                    COUNT(issue_id) as issues
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id = :repo_id
                AND issues.created_at BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS') AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY date, repo_name
                ORDER BY date;
            """)

            results = pd.read_sql(issues_new_SQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                   'begin_date': begin_date, 'end_date': end_date})
            return results

    @annotate(tag='issues-active')
    def issues_active(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """Returns a timeseries of issues active.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of issues active/period
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not repo_id:
            issues_active_SQL = s.sql.text("""
                SELECT
                    issues.repo_id,
                    repo_name,
                    date_trunc(:period, issue_events.created_at) as date,
                    COUNT(issues.issue_id) AS issues
                FROM issues, repo, issue_events
                WHERE issues.issue_id = issue_events.issue_id
                AND issues.repo_id = repo.repo_id
                AND issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND issue_events.created_at BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS') AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY issues.repo_id, date, repo_name
                ORDER BY issues.repo_id, date
            """)

            results = pd.read_sql(issues_active_SQL, self.db, params={'repo_group_id': repo_group_id, 'period':period,
                                                                      'begin_date': begin_date, 'end_date':end_date})
            return results

        else:
            issues_active_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    date_trunc(:period, issue_events.created_at) as date,
                    COUNT(issues.issue_id) AS issues
                FROM issues, repo, issue_events
                WHERE issues.issue_id = issue_events.issue_id
                AND issues.repo_id = repo.repo_id
                AND issues.repo_id = :repo_id
                AND issue_events.created_at BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS') AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY date, repo_name
                ORDER BY date
            """)

            results = pd.read_sql(issues_active_SQL, self.db, params={'repo_id': repo_id, 'period':period,
                                                                      'begin_date': begin_date, 'end_date':end_date})
            return results

    @annotate(tag='issues-closed')
    def issues_closed(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """Returns a timeseries of issues closed.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param period: To set the periodicity to 'day', 'week', 'month' or 'year', defaults to 'day'
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of issues closed/period
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not repo_id:
            issues_closed_SQL = s.sql.text("""
                SELECT
                    issues.repo_id,
                    repo_name,
                    date_trunc(:period, closed_at::DATE) as date,
                    COUNT(issue_id) as issues
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND closed_at IS NOT NULL
                AND closed_at BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS') AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY issues.repo_id, date, repo_name
                ORDER BY issues.repo_id, date
            """)

            results = pd.read_sql(issues_closed_SQL, self.db, params={'repo_group_id': repo_group_id, 'period': period,
                                                                       'begin_date': begin_date, 'end_date': end_date})

            return results

        else:
            issues_closed_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    date_trunc(:period, closed_at::DATE) as date,
                    COUNT(issue_id) as issues
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id = :repo_id
                AND closed_at IS NOT NULL
                AND closed_at BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS') AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY date, repo_name
                ORDER BY date;
            """)

            results = pd.read_sql(issues_closed_SQL, self.db, params={'repo_id': repo_id, 'period': period,
                                                                    'begin_date': begin_date, 'end_date': end_date})
            return results

    @annotate(tag='issue-duration')
    def issue_duration(self, repo_group_id, repo_id=None, begin_date=None, end_date=None):
        """Returns the duration of each issue.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of issue id with the corresponding duration
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not repo_id:
            issue_duration_SQL = s.sql.text("""
                SELECT
                    issues.repo_id,
                    repo_name,
                    issue_id,
                    issues.created_at,
                    issues.closed_at,
                    (issues.closed_at - issues.created_at) AS duration
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND closed_at IS NOT NULL
                AND issues.created_at
                    BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS')
                    AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                ORDER BY repo_id, issue_id
            """)

            results = pd.read_sql(issue_duration_SQL, self.db, params={'repo_group_id': repo_group_id,
                                                                       'begin_date': begin_date,
                                                                       'end_date': end_date})
            results['duration'] = results['duration'].astype(str)
            return results

        else:
            issue_duration_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    issue_id,
                    issues.created_at,
                    issues.closed_at,
                    (closed_at - issues.created_at) AS duration
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id = :repo_id
                AND closed_at IS NOT NULL
                AND issues.created_at
                    BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS')
                    AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                ORDER BY issue_id;
            """)

            results = pd.read_sql(issue_duration_SQL, self.db, params={'repo_id': repo_id,
                                                                       'begin_date': begin_date,
                                                                       'end_date': end_date})
            results['duration'] = results['duration'].astype(str)
            return results

    @annotate(tag='issue-participants')
    def issue_participants(self, repo_group_id, repo_id=None, begin_date=None, end_date=None):
        """Returns number of participants per issue.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param begin_date: Specifies the begin date, defaults to '1970-1-1 00:00:00'
        :param end_date: Specifies the end date, defaults to datetime.now()
        :return: DataFrame of count of participants per issue.
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:00'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not repo_id:
            issue_participants_SQL = s.sql.text("""
                SELECT
                    issues.repo_id,
                    repo.repo_name,
                    derived.issue_id,
                    issues.created_at,
                    COUNT(DISTINCT derived.cntrb_id) AS participants
                FROM (
                    (SELECT issue_id, cntrb_id FROM issues WHERE cntrb_id IS NOT NULL)
                    UNION
                    (SELECT issue_id, cntrb_id FROM issue_message_ref, message
                    WHERE issue_message_ref.msg_id = message.msg_id)
                ) AS derived, issues, repo
                WHERE derived.issue_id = issues.issue_id
                AND issues.repo_id = repo.repo_id
                AND issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND issues.created_at
                    BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS')
                    AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY issues.repo_id, repo_name, derived.issue_id, issues.created_at
                ORDER BY issues.repo_id, issues.created_at
            """)

            result = pd.read_sql(issue_participants_SQL, self.db, params={'repo_group_id': repo_group_id,
                                                                          'begin_date': begin_date,
                                                                          'end_date': end_date})
            return result
        else:
            issue_participants_SQL = s.sql.text("""
                SELECT
                    repo.repo_name,
                    derived.issue_id,
                    issues.created_at,
                    COUNT(DISTINCT derived.cntrb_id) AS participants
                FROM (
                    (SELECT issue_id, cntrb_id FROM issues WHERE cntrb_id IS NOT NULL)
                    UNION
                    (SELECT issue_id, cntrb_id FROM issue_message_ref, message
                    WHERE issue_message_ref.msg_id = message.msg_id)
                ) AS derived, issues, repo
                WHERE derived.issue_id = issues.issue_id
                AND issues.repo_id = repo.repo_id
                AND issues.repo_id = :repo_id
                AND issues.created_at
                    BETWEEN to_timestamp(:begin_date, 'YYYY-MM-DD HH24:MI:SS')
                    AND to_timestamp(:end_date, 'YYYY-MM-DD HH24:MI:SS')
                GROUP BY repo_name, derived.issue_id, issues.created_at
                ORDER BY issues.created_at
            """)

            result = pd.read_sql(issue_participants_SQL, self.db, params={'repo_id': repo_id,
                                                                          'begin_date': begin_date,
                                                                          'end_date': end_date})
            return result

    @annotate(tag='issue-backlog')
    def issue_backlog(self, repo_group_id, repo_id=None):
        """Returns number of issues currently open.

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: DataFrame of count of issues currently open.
        """
        if not repo_id:
            issue_backlog_SQL = s.sql.text("""
                SELECT issues.repo_id, repo_name, COUNT(issue_id) as issue_backlog
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id IN (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
                AND issue_state = 'open'
                GROUP BY issues.repo_id, repo_name
                ORDER BY issues.repo_id
            """)
            result = pd.read_sql(issue_backlog_SQL, self.db, params={'repo_group_id': repo_group_id})
            return result

        else:
            issue_backlog_SQL = s.sql.text("""
                SELECT repo_name, COUNT(issue_id) as issue_backlog
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id = :repo_id
                AND issue_state='open'
                GROUP BY repo_name
            """)

            result = pd.read_sql(issue_backlog_SQL, self.db, params={'repo_id': repo_id})
            return result

    @annotate(tag='issue-throughput')
    def issue_throughput(self, repo_group_id, repo_id=None):
        """Returns the ratio of issues closed to total issues

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: DataFrame of ratio of issues closed to total issues.
        """
        if not repo_id:
            issue_throughput_SQL = s.sql.text("""
                SELECT table1.repo_id, repo.repo_name, (tot1 / tot2) AS throughput
                FROM
                    (SELECT repo_id, COUNT(issue_id)::REAL AS tot1
                    FROM issues WHERE issue_state='closed'
                    AND repo_id IN (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
                    GROUP BY repo_id) AS table1,
                    (SELECT repo_id, COUNT(issue_id)::REAL AS tot2
                    FROM issues
                    WHERE repo_id IN (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
                    GROUP BY repo_id) AS table2,
                    repo
                WHERE table1.repo_id = table2.repo_id
                AND table1.repo_id = repo.repo_id
            """)

            results = pd.read_sql(issue_throughput_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            issue_throughput_SQL = s.sql.text("""
                SELECT repo.repo_name, (tot1 / tot2) AS throughput
                FROM
                    (SELECT repo_id, COUNT(issue_id)::REAL AS tot1 FROM issues
                    WHERE issue_state='closed' AND repo_id=:repo_id
                    GROUP BY repo_id) AS table1,
                    (SELECT COUNT(issue_id)::REAL AS tot2 FROM issues
                    WHERE repo_id=:repo_id) AS table2,
                    repo
                WHERE table1.repo_id = repo.repo_id
            """)

            result = pd.read_sql(issue_throughput_SQL, self.db, params={'repo_id': repo_id})
            return result

    @annotate(tag='issues-open-age')
    def issues_open_age(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Retrun the age of open issues

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: DataFrame of age of open issues.
        """

        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        openAgeSQL = None

        if not repo_id:
            openAgeSQL = s.sql.text("""
                SELECT  repo.repo_id, repo_name, issue_id, date_trunc(:period, issues.created_at ) as date, EXTRACT(DAY FROM NOW() - issues.created_at) AS open_date
                FROM issues,
                    repo,
                    repo_groups
                WHERE issue_state = 'open'
                AND issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND repo.repo_id = issues.repo_id
                AND issues.created_at BETWEEN :begin_date and :end_date
                GROUP BY repo.repo_id, repo_name, issue_id, date, open_date
                ORDER BY open_date DESC
            """)
        else:
            openAgeSQL = s.sql.text("""
                SELECT repo.repo_id, repo_name, issue_id, date_trunc(:period, issues.created_at ) as date, EXTRACT(DAY FROM NOW() - issues.created_at) AS open_date
                FROM issues,
                    repo,
                    repo_groups
                WHERE issue_state = 'open'
                AND issues.repo_id = :repo_id
                AND repo.repo_id = issues.repo_id
                AND issues.created_at BETWEEN :begin_date and :end_date
                GROUP BY repo.repo_id,issue_id, date, open_date
                ORDER BY open_date DESC
            """)

        results = pd.read_sql(openAgeSQL, self.db,
                                params={'repo_id': repo_id, 'repo_group_id': repo_group_id,
                                'period': period, 'begin_date':begin_date, 'end_date':end_date})

        return results

    @annotate(tag='issues-closed-resolution-duration')
    def issues_closed_resolution_duration(self, repo_group_id, repo_id=None, period='day', begin_date=None, end_date=None):
        """
        Retrun Time duration of time for issues to be resolved

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: DataFrame of time duration of time for issues to be resolved
        """
        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        issueSQL = None
        if not repo_id:
            issueSQL = s.sql.text("""
               SELECT repo.repo_id,
                    repo_name,
                    gh_issue_number,
                    issue_title,
                    date_trunc(:period, issues.created_at) as created_at,
                    date_trunc(:period, issues.closed_at) as closed_at,
                    EXTRACT(DAY FROM closed_at - issues.created_at) AS DIFFDATE
                FROM issues,
                    repo
                WHERE issues.closed_at NOTNULL
                AND issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND repo.repo_id = issues.repo_id
                AND issues.created_at BETWEEN :begin_date and :end_date
                GROUP BY repo.repo_id, repo.repo_name, gh_issue_number, issue_title, issues.created_at, issues.closed_at, DIFFDATE
                ORDER BY gh_issue_number
            """)
        else:
            issueSQL = s.sql.text("""
                SELECT repo.repo_id,
                    repo_name,
                    gh_issue_number,
                    issue_title,
                    date_trunc(:period, issues.created_at) as created_at,
                    date_trunc(:period, issues.closed_at) as closed_at,
                    EXTRACT(DAY FROM closed_at - issues.created_at) AS DIFFDATE
                FROM issues,
                    repo
                WHERE issues.closed_at NOTNULL
                AND issues.repo_id = :repo_id
                AND repo.repo_id = issues.repo_id
                AND issues.created_at BETWEEN :begin_date and :end_date
                GROUP BY repo.repo_id, repo.repo_name, gh_issue_number, issue_title, issues.created_at, issues.closed_at, DIFFDATE
                ORDER BY gh_issue_number
            """)

        results = pd.read_sql(issueSQL, self.db,
                                params={'repo_id': repo_id,
                                'repo_group_id': repo_group_id,
                                'period': period, 'begin_date':begin_date,
                                'end_date':end_date})

        return results

    #####################################
    ###              RISK             ###
    #####################################

    @annotate(tag='cii-best-practices-badge')
    def cii_best_practices_badge(self, repo_group_id, repo_id=None):
        """Returns the CII best practices badge level

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: CII best parctices badge level
        """
        if not repo_id:
            cii_best_practices_badge_SQL = s.sql.text("""
                SELECT repo_badging.repo_id, repo_name, badge_level
                FROM repo_badging JOIN repo ON repo_badging.repo_id = repo.repo_id
                WHERE repo_badging.repo_id IN (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
            """)

            results = pd.read_sql(cii_best_practices_badge_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            cii_best_practices_badge_SQL = s.sql.text("""
                SELECT repo_name, badge_level
                FROM repo_badging JOIN repo ON repo_badging.repo_id = repo.repo_id
                WHERE repo_badging.repo_id = :repo_id
            """)

            results = pd.read_sql(cii_best_practices_badge_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='average-issue-resolution-time')
    def average_issue_resolution_time(self, repo_group_id, repo_id=None):
        """
        Returns the average issue resolution time

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Average issue resolution time
        """
        if not repo_id:
            avg_issue_resolution_SQL = s.sql.text("""
                SELECT
                    issues.repo_id,
                    repo.repo_name,
                    AVG(issues.closed_at - issues.created_at)::text AS avg_issue_resolution_time
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id IN
                    (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
                AND closed_at IS NOT NULL
                GROUP BY issues.repo_id, repo.repo_name
                ORDER BY issues.repo_id
            """)

            results = pd.read_sql(avg_issue_resolution_SQL, self.db,
                                  params={'repo_group_id': repo_group_id})
            return results

        else:
            avg_issue_resolution_SQL = s.sql.text("""
                SELECT
                    repo.repo_name,
                    AVG(issues.closed_at - issues.created_at)::text AS avg_issue_resolution_time
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id
                WHERE issues.repo_id = :repo_id
                AND closed_at IS NOT NULL
                GROUP BY repo.repo_name
            """)

            results = pd.read_sql(avg_issue_resolution_SQL, self.db,
                                  params={'repo_id': repo_id})
            return results

    @annotate(tag='forks')
    def forks(self, repo_group_id, repo_id=None):
        """
        Returns a time series of the fork count

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Time series of fork count
        """
        if not repo_id:
            forks_SQL = s.sql.text("""
                SELECT
                    repo_info.repo_id,
                    repo_name,
                    repo_info.data_collection_date as date,
                    fork_count AS forks
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id IN
                    (SELECT repo_id FROM repo
                     WHERE  repo_group_id = :repo_group_id)
                ORDER BY repo_info.repo_id, date
            """)

            results = pd.read_sql(forks_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            forks_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    repo_info.data_collection_date as date,
                    fork_count AS forks
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id = :repo_id
                ORDER BY date
            """)

            results = pd.read_sql(forks_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='fork-count')
    def fork_count(self, repo_group_id, repo_id=None):
        """
        Returns the latest fork count

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Fork count
        """
        if not repo_id:
            fork_count_SQL = s.sql.text("""
                SELECT a.repo_id, repo_name, a.fork_count AS forks
                FROM repo_info a LEFT JOIN repo_info b
                ON (a.repo_id = b.repo_id AND a.repo_info_id < b.repo_info_id), repo
                WHERE b.repo_info_id IS NULL
                AND a.repo_id = repo.repo_id
                AND a.repo_id IN
                    (SELECT repo_id FROM repo
                     WHERE  repo_group_id = :repo_group_id)
            """)

            results = pd.read_sql(fork_count_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results
        else:
            fork_count_SQL = s.sql.text("""
                SELECT repo_name, fork_count AS forks
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id = :repo_id
                ORDER BY repo_info.data_collection_date DESC
                LIMIT 1
            """)

            results = pd.read_sql(fork_count_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='languages')
    def languages(self, repo_group_id, repo_id=None):
        """Returns the implementation languages

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Implementation languages
        """
        if not repo_id:
            languages_SQL = s.sql.text("""
                SELECT repo_name, repo_id, primary_language
                FROM repo
                WHERE repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
            """)

            results = pd.read_sql(languages_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            languages_SQL = s.sql.text("""
                SELECT repo_name, primary_language
                FROM repo
                WHERE repo_id = :repo_id
            """)

            results = pd.read_sql(languages_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='license-declared')
    def license_declared(self, repo_group_id, repo_id=None):
        """Returns the declared license

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Declared License
        """
        if not repo_id:
            license_declared_SQL = s.sql.text("""
                SELECT repo_badging.repo_id, repo_name, license
                FROM repo_badging JOIN repo ON repo_badging.repo_id = repo.repo_id
                WHERE repo_badging.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id);
            """)

            results = pd.read_sql(license_declared_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            license_declared_SQL = s.sql.text("""
                SELECT repo_name, license
                FROM repo_badging JOIN repo ON repo_badging.repo_id = repo.repo_id
                WHERE repo_badging.repo_id = :repo_id;
            """)

            results = pd.read_sql(license_declared_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='issues-maintainer-response-duration')
    def issues_maintainer_response_duration(self, repo_group_id, repo_id=None, begin_date=None, end_date=None):

        if not begin_date:
            begin_date = '1970-1-1 00:00:01'
        if not end_date:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        issuesSQL = None
        if repo_id:
            issuesSQL = s.sql.text("""
                select repo_id, repo_name, AVG(time_to_first_commit) as average_days_comment
                from (
                        select repo_id,
                                repo_name,
                                earliest_member_comments.issue_id                  as issue_id,
                                extract(day from first_response_time - created_at) as time_to_first_commit
                        from (
                                select issues.issue_id            as issue_id,
                                        issues.created_at          as created_at,
                                        MIN(message.msg_timestamp) as first_response_time,
                                        repo_name,
                                        repo.repo_id
                                from repo,
                                    issues,
                                    issue_message_ref,
                                    message
                                where repo.repo_id = :repo_id
                                    and repo.repo_id = issues.repo_id
                                    and issues.issue_id = issue_message_ref.issue_id
                                    and issue_message_ref.msg_id = message.msg_id
                                    and issues.created_at between :begin_date and :end_date
                                group by issues.issue_id, issues.created_at, repo.repo_id
                            ) as earliest_member_comments
                        group by repo_id, repo_name,issue_id, time_to_first_commit
                    ) as time_to_comment
                group by repo_id, repo_name
            """)
        else:
            issuesSQL = s.sql.text("""
                select repo_id, repo_name, AVG(time_to_first_commit) as average_days_comment
                from (
                        select repo_id,
                                repo_name,
                                earliest_member_comments.issue_id                  as issue_id,
                                extract(day from first_response_time - created_at) as time_to_first_commit
                        from (
                                select issues.issue_id            as issue_id,
                                        issues.created_at          as created_at,
                                        MIN(message.msg_timestamp) as first_response_time,
                                        repo_name,
                                        repo.repo_id
                                from repo,
                                    issues,
                                    issue_message_ref,
                                    message
                                where repo.repo_id IN (SELECT repo.repo_id from repo where repo_group_id = :repo_group_id)
                                    and repo.repo_id = issues.repo_id
                                    and issues.issue_id = issue_message_ref.issue_id
                                    and issue_message_ref.msg_id = message.msg_id
                                    and issues.created_at between :begin_date and :end_date
                                group by issues.issue_id, issues.created_at, repo.repo_id
                            ) as earliest_member_comments
                        group by repo_id, repo_name,issue_id, time_to_first_commit
                    ) as time_to_comment
                group by repo_id, repo_name
            """)

        results = pd.read_sql(issuesSQL, self.db, params={'repo_id': repo_id, 'repo_group_id': repo_group_id,'begin_date': begin_date, 'end_date': end_date})

        return results

    #####################################
    ###             VALUE             ###
    #####################################

    @annotate(tag='stars')
    def stars(self, repo_group_id, repo_id=None):
        """
        Returns a time series of the stars count

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Time series of stars count
        """
        if not repo_id:
            stars_SQL = s.sql.text("""
                SELECT
                    repo_info.repo_id,
                    repo_name,
                    repo_info.data_collection_date as date,
                    stars_count AS stars
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id IN
                    (SELECT repo_id FROM repo
                     WHERE  repo_group_id = :repo_group_id)
                ORDER BY repo_info.repo_id, date
            """)

            results = pd.read_sql(stars_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            stars_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    repo_info.data_collection_date as date,
                    stars_count AS stars
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id = :repo_id
                ORDER BY date
            """)

            results = pd.read_sql(stars_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='stars-count')
    def stars_count(self, repo_group_id, repo_id=None):
        """
        Returns the latest stars count

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: stars count
        """
        if not repo_id:
            stars_count_SQL = s.sql.text("""
                SELECT a.repo_id, repo_name, a.stars_count AS stars
                FROM repo_info a LEFT JOIN repo_info b
                ON (a.repo_id = b.repo_id AND a.repo_info_id < b.repo_info_id), repo
                WHERE b.repo_info_id IS NULL
                AND a.repo_id = repo.repo_id
                AND a.repo_id IN
                    (SELECT repo_id FROM repo
                     WHERE  repo_group_id = :repo_group_id)
            """)

            results = pd.read_sql(stars_count_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results
        else:
            stars_count_SQL = s.sql.text("""
                SELECT repo_name, stars_count AS stars
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id = :repo_id
                ORDER BY repo_info.data_collection_date DESC
                LIMIT 1
            """)

            results = pd.read_sql(stars_count_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='watchers')
    def watchers(self, repo_group_id, repo_id=None):
        """
        Returns a time series of the watchers count

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: Time series of watchers count
        """
        if not repo_id:
            watchers_SQL = s.sql.text("""
                SELECT
                    repo_info.repo_id,
                    repo_name,
                    repo_info.data_collection_date as date,
                    watchers_count AS watchers
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id IN
                    (SELECT repo_id FROM repo
                     WHERE  repo_group_id = :repo_group_id)
                ORDER BY repo_info.repo_id, date
            """)

            results = pd.read_sql(watchers_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results

        else:
            watchers_SQL = s.sql.text("""
                SELECT
                    repo_name,
                    repo_info.data_collection_date as date,
                    watchers_count AS watchers
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id = :repo_id
                ORDER BY date
            """)

            results = pd.read_sql(watchers_SQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='watchers-count')
    def watchers_count(self, repo_group_id, repo_id=None):
        """
        Returns the latest watchers count

        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :return: watchers count
        """
        if not repo_id:
            watchers_count_SQL = s.sql.text("""
                SELECT a.repo_id, repo_name, a.watchers_count AS watchers
                FROM repo_info a LEFT JOIN repo_info b
                ON (a.repo_id = b.repo_id AND a.repo_info_id < b.repo_info_id), repo
                WHERE b.repo_info_id IS NULL
                AND a.repo_id = repo.repo_id
                AND a.repo_id IN
                    (SELECT repo_id FROM repo
                     WHERE  repo_group_id = :repo_group_id)
            """)

            results = pd.read_sql(watchers_count_SQL, self.db, params={'repo_group_id': repo_group_id})
            return results
        else:
            watchers_count_SQL = s.sql.text("""
                SELECT repo_name, watchers_count AS watchers
                FROM repo_info JOIN repo ON repo_info.repo_id = repo.repo_id
                WHERE repo_info.repo_id = :repo_id
                ORDER BY repo_info.data_collection_date DESC
                LIMIT 1
            """)

            results = pd.read_sql(watchers_count_SQL, self.db, params={'repo_id': repo_id})
            return results

    #####################################
    ###         EXPERIMENTAL          ###
    #####################################

    @annotate(tag='lines-changed-by-author')
    def lines_changed_by_author(self, repo_group_id, repo_id = None):
        """
        Returns number of lines changed per author per day

        :param repo_url: the repository's URL
        """

        if repo_id:
            linesChangedByAuthorSQL = s.sql.text("""
                SELECT cmt_author_email, cmt_author_date, cmt_author_affiliation as affiliation,
                    SUM(cmt_added) as additions, SUM(cmt_removed) as deletions, SUM(cmt_whitespace) as whitespace, repo_name
                FROM commits JOIN repo ON commits.repo_id = repo.repo_id
                WHERE commits.repo_id = :repo_id
                GROUP BY commits.repo_id, cmt_author_date, cmt_author_affiliation, cmt_author_email, repo_name
                ORDER BY cmt_author_date ASC;
            """)
            results = pd.read_sql(linesChangedByAuthorSQL, self.db, params={"repo_id": repo_id})
            return results
        else:
            linesChangedByAuthorSQL = s.sql.text("""
                SELECT cmt_author_email, cmt_author_date, cmt_author_affiliation as affiliation,
                    SUM(cmt_added) as additions, SUM(cmt_removed) as deletions, SUM(cmt_whitespace) as whitespace
                FROM commits
                WHERE repo_id in (SELECT repo_id FROM repo WHERE repo_group_id=:repo_group_id)
                GROUP BY repo_id, cmt_author_date, cmt_author_affiliation, cmt_author_email
                ORDER BY cmt_author_date ASC;
            """)
            results = pd.read_sql(linesChangedByAuthorSQL, self.db, params={"repo_group_id": repo_group_id})
            return results

    @annotate(tag='closed-issues-count')
    def open_issues_count(self, repo_group_id, repo_id=None):
        """
        Returns number of lines changed per author per day

        :param repo_url: the repository's URL
        """
        if not repo_id:
            openIssueCountSQL = s.sql.text("""
                SELECT rg_name, count(issue_id) AS open_count, date_trunc('week', issues.created_at) AS DATE
                FROM issues, repo, repo_groups
                WHERE issue_state = 'open'
                AND issues.repo_id IN (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
                AND repo.repo_id = issues.repo_id
                AND repo.repo_group_id = repo_groups.repo_group_id
                GROUP BY date, repo_groups.rg_name
                ORDER BY date
            """)
            results = pd.read_sql(openIssueCountSQL, self.db, params={'repo_group_id': repo_group_id})
            return results
        else:
            openIssueCountSQL = s.sql.text("""
                SELECT repo.repo_id, count(issue_id) AS open_count, date_trunc('week', issues.created_at) AS DATE, repo_name
                FROM issues, repo, repo_groups
                WHERE issue_state = 'open'
                AND issues.repo_id = :repo_id
                AND repo.repo_id = issues.repo_id
                AND repo.repo_group_id = repo_groups.repo_group_id
                GROUP BY date, repo.repo_id
                ORDER BY date
            """)
            results = pd.read_sql(openIssueCountSQL, self.db, params={'repo_id': repo_id})
            return results


    @annotate(tag='closed-issues-count')
    def closed_issues_count(self, repo_group_id, repo_id=None):
        """
        Returns number of lines changed per author per day

        :param repo_url: the repository's URL
        """
        if not repo_id:
            closedIssueCountSQL = s.sql.text("""
                SELECT rg_name, count(issue_id) AS closed_count, date_trunc('week', issues.created_at) AS DATE
                FROM issues, repo, repo_groups
                WHERE issue_state = 'closed'
                AND issues.repo_id IN (SELECT repo_id FROM repo WHERE  repo_group_id = :repo_group_id)
                AND repo.repo_id = issues.repo_id
                AND repo.repo_group_id = repo_groups.repo_group_id
                GROUP BY date, repo_groups.rg_name
                ORDER BY date
            """)
            results = pd.read_sql(closedIssueCountSQL, self.db, params={'repo_group_id': repo_group_id})
            return results
        else:
            closedIssueCountSQL = s.sql.text("""
                SELECT repo.repo_id, count(issue_id) AS closed_count, date_trunc('week', issues.created_at) AS DATE, repo_name
                FROM issues, repo, repo_groups
                WHERE issue_state = 'closed'
                AND issues.repo_id = :repo_id
                AND repo.repo_id = issues.repo_id
                AND repo.repo_group_id = repo_groups.repo_group_id
                GROUP BY date, repo.repo_id
                ORDER BY date
            """)
            results = pd.read_sql(closedIssueCountSQL, self.db, params={'repo_id': repo_id})
            return results

    @annotate(tag='annual-commit-count-ranked-by-new-repo-in-repo-group')
    def annual_commit_count_ranked_by_new_repo_in_repo_group(self, repo_group_id, repo_id = None, calendar_year=None):
        """
        For each repository in a collection of repositories being managed, each REPO that first appears in the parameterized
        calendar year (a new repo in that year), show all commits for that year (total for year by repo).
        Result ranked from highest number of commits to lowest by default.

        :param repo_url: the repository's URL
        :param calendar_year: the calendar year a repo is created in to be considered "new"
        :param repo_group: the group of repositories to analyze
        """
        if calendar_year == None:
            calendar_year = 2019

        cdRgNewrepRankedCommitsSQL = None

        if not repo_id:
            cdRgNewrepRankedCommitsSQL = s.sql.text("""
                SELECT repo.repo_id, sum(cast(added as INTEGER) - cast(removed as INTEGER) - cast(whitespace as INTEGER)) as net, patches, repo_name
                FROM dm_repo_annual, repo, repo_groups
                where  repo.repo_group_id = :repo_group_id
                and dm_repo_annual.repo_id = repo.repo_id
                and date_part('year', repo.repo_added) = :calendar_year
                and repo.repo_group_id = repo_groups.repo_group_id
                group by repo.repo_id, patches, rg_name
                ORDER BY net desc
                LIMIT 10
            """)
        else:
            cdRgNewrepRankedCommitsSQL = s.sql.text("""
                SELECT repo.repo_id, sum(cast(added as INTEGER) - cast(removed as INTEGER) - cast(whitespace as INTEGER)) as net, patches, repo_name
                FROM dm_repo_annual, repo, repo_groups
                where  repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                and dm_repo_annual.repo_id = repo.repo_id
                and date_part('year', repo.repo_added) = :calendar_year
                and repo.repo_group_id = repo_groups.repo_group_id
                group by repo.repo_id, patches, rg_name
                ORDER BY net desc
                LIMIT 10
            """)
        results = pd.read_sql(cdRgNewrepRankedCommitsSQL, self.db, params={ "repo_group_id": repo_group_id,
        "repo_id": repo_id, "calendar_year": calendar_year})
        return results

    @annotate(tag='annual-commit-count-ranked-by-repo-in-repo-group')
    def annual_commit_count_ranked_by_repo_in_repo_group(self, repo_group_id, repo_id=None, timeframe=None):
        """
        For each repository in a collection of repositories being managed, each REPO's total commits during the current Month,
        Year or Week. Result ranked from highest number of commits to lowest by default.
        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param calendar_year: the calendar year a repo is created in to be considered "new"
        """
        if timeframe == None:
            timeframe = 'all'

        cdRgTpRankedCommitsSQL = None

        if repo_id:
            if timeframe == 'all':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
            elif timeframe == 'year':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
            elif timeframe == 'month':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_monthly, repo, repo_groups
                    WHERE repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_monthly.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    AND date_part('month', repo_added) = date_part('month', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
        else:
            if timeframe == 'all':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = :repo_group_id
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
            elif timeframe == "year":
                cdRgTpRankedCommitsSQL = s.sql.text(
                    """
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = :repo_group_id
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                    """
                )
            elif timeframe == 'month':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = :repo_group_id
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    AND date_part('month', repo_added) = date_part('month', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)


        results = pd.read_sql(cdRgTpRankedCommitsSQL, self.db, params={ "repo_group_id": repo_group_id,
        "repo_id": repo_id})
        return results

    @annotate(tag='annual-lines-of-code-count-ranked-by-new-repo-in-repo-group')
    def annual_lines_of_code_count_ranked_by_new_repo_in_repo_group(self, repo_group_id, repo_id = None, calendar_year=None):
        """
        For each repository in a collection of repositories being managed, each REPO that first appears in the parameterized
    calendar year (a new repo in that year), show all commits for that year (total for year by repo).
        Result ranked from highest number of commits to lowest by default.

        :param repo_url: the repository's URL
        :param calendar_year: the calendar year a repo is created in to be considered "new"
        :param repo_group: the group of repositories to analyze
        """
        if calendar_year == None:
            calendar_year = 2019

        cdRgNewrepRankedCommitsSQL = None

        if not repo_id:
            cdRgNewrepRankedCommitsSQL = s.sql.text("""
                SELECT repo.repo_id, sum(cast(added as INTEGER) - cast(removed as INTEGER) - cast(whitespace as INTEGER)) as net, patches, repo_name
                FROM dm_repo_annual, repo, repo_groups
                where  repo.repo_group_id = :repo_group_id
                and dm_repo_annual.repo_id = repo.repo_id
                and date_part('year', repo.repo_added) = :calendar_year
                and repo.repo_group_id = repo_groups.repo_group_id
                group by repo.repo_id, patches, rg_name
                ORDER BY net desc
                LIMIT 10
            """)
        else:
            cdRgNewrepRankedCommitsSQL = s.sql.text("""
                SELECT repo.repo_id, sum(cast(added as INTEGER) - cast(removed as INTEGER) - cast(whitespace as INTEGER)) as net, patches, repo_name
                FROM dm_repo_annual, repo, repo_groups
                where  repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                and dm_repo_annual.repo_id = repo.repo_id
                and date_part('year', repo.repo_added) = :calendar_year
                and repo.repo_group_id = repo_groups.repo_group_id
                group by repo.repo_id, patches, rg_name
                ORDER BY net desc
                LIMIT 10
            """)
        results = pd.read_sql(cdRgNewrepRankedCommitsSQL, self.db, params={ "repo_group_id": repo_group_id,
        "repo_id": repo_id, "calendar_year": calendar_year})
        return results

    @annotate(tag='annual-lines-of-code-count-ranked-by-repo-in-repo-group')
    def annual_lines_of_code_count_ranked_by_repo_in_repo_group(self, repo_group_id, repo_id=None, timeframe=None):
        """
        For each repository in a collection of repositories being managed, each REPO's total commits during the current Month,
        Year or Week. Result ranked from highest number of commits to lowest by default.
        :param repo_group_id: The repository's repo_group_id
        :param repo_id: The repository's repo_id, defaults to None
        :param calendar_year: the calendar year a repo is created in to be considered "new"
        """
        if timeframe == None:
            timeframe = 'all'

        cdRgTpRankedCommitsSQL = None

        if repo_id:
            if timeframe == 'all':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
            elif timeframe == 'year':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
            elif timeframe == 'month':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_monthly, repo, repo_groups
                    WHERE repo.repo_group_id = (select repo.repo_group_id from repo where repo.repo_id = :repo_id)
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_monthly.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    AND date_part('month', repo_added) = date_part('month', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
        else:
            if timeframe == 'all':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = :repo_group_id
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)
            elif timeframe == "year":
                cdRgTpRankedCommitsSQL = s.sql.text(
                    """
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = :repo_group_id
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                    """
                )
            elif timeframe == 'month':
                cdRgTpRankedCommitsSQL = s.sql.text("""
                    SELECT repo.repo_id, repo_name as name, SUM(added - removed - whitespace) as net, patches
                    FROM dm_repo_annual, repo, repo_groups
                    WHERE repo.repo_group_id = :repo_group_id
                    AND repo.repo_group_id = repo_groups.repo_group_id
                    AND dm_repo_annual.repo_id = repo.repo_id
                    AND date_part('year', repo_added) = date_part('year', CURRENT_DATE)
                    AND date_part('month', repo_added) = date_part('month', CURRENT_DATE)
                    group by repo.repo_id, patches
                    order by net desc
                    LIMIT 10
                """)


        results = pd.read_sql(cdRgTpRankedCommitsSQL, self.db, params={ "repo_group_id": repo_group_id,
        "repo_id": repo_id})
        return results

    @annotate(tag='top-committers')
    def top_committers(self, repo_group_id, repo_id=None, year=None, threshold=0.5):
        """
        Returns a list of contributors contributing N% of all commits.

        :param repo_group_id: Repo group ID
        :param repo_id: Repo ID.
        :param year: Year. eg: 2018, 2107. Defaults to current year.
        :param threshold: The threshold to specify N%. Defaults to 0.5
        """
        threshold = float(threshold)
        if threshold < 0 or threshold > 1:
            raise ValueError('threshold should be between 0 and 1')

        if year is None:
            year = datetime.datetime.now().year

        if not repo_id:
            total_commits_SQL = s.sql.text("""
                SELECT SUM(patches)::int
                FROM
                    (SELECT repo_group_id, email, year, patches
                    FROM dm_repo_group_annual
                    WHERE year = :year AND repo_group_id = :repo_group_id
                    ORDER BY patches DESC) a
            """)

            results = pd.read_sql(total_commits_SQL, self.db,
                                params={'year': year, 'repo_group_id': repo_group_id})
        else:
            total_commits_SQL = s.sql.text("""
                SELECT SUM(patches)::int
                FROM
                    (SELECT repo_id, email, year, patches
                    FROM dm_repo_annual
                    WHERE year = :year AND repo_id = :repo_id
                    ORDER BY patches DESC) a
            """)

            results = pd.read_sql(total_commits_SQL, self.db,
                                params={'year': year, 'repo_id': repo_id})

        total_commits = int(results.iloc[0]['sum'])
        threshold_commits = round(threshold * total_commits)

        if not repo_id:
            committers_SQL = s.sql.text("""
                SELECT
                    a.repo_group_id,
                    rg_name AS repo_group_name,
                    a.email,
                    SUM(a.patches)::int AS commits
                FROM
                    (SELECT repo_group_id, email, year, patches
                    FROM dm_repo_group_annual
                    WHERE year = :year AND repo_group_id = :repo_group_id
                    ORDER BY patches DESC) a, repo_groups
                WHERE a.repo_group_id = repo_groups.repo_group_id
                GROUP BY a.repo_group_id, repo_group_name, a.email
                ORDER BY commits DESC
            """)

            results = pd.read_sql(committers_SQL, self.db,
                                params={'year': year, 'repo_group_id': repo_group_id})
        else:
            committers_SQL = s.sql.text("""
                SELECT
                    a.repo_id,
                    repo.repo_name,
                    a.email,
                    SUM(a.patches)::int AS commits
                FROM
                    (SELECT repo_id, email, year, patches
                    FROM dm_repo_annual
                    WHERE year = :year AND repo_id = :repo_id
                    ORDER BY patches DESC) a, repo
                WHERE a.repo_id = repo.repo_id
                GROUP BY a.repo_id, repo.repo_name, a.email
                ORDER BY commits DESC
            """)

            results = pd.read_sql(committers_SQL, self.db,
                                  params={'year': year, 'repo_id': repo_id})

        cumsum = 0
        for i, row in results.iterrows():
            cumsum += row['commits']
            if cumsum >= threshold_commits:
                results = results[:i + 1]
                break

        if not repo_id:
            rg_name = results.iloc[0]['repo_group_name']
            results.loc[i+1] = [repo_group_id, rg_name, 'other_contributors',
                                int(total_commits - cumsum)]
        else:
            repo_name = results.iloc[0]['repo_name']
            results.loc[i+1] = [repo_id, repo_name, 'other_contributors',
                                int(total_commits - cumsum)]

        return results

#####################################
###           UTILITIES           ###
#####################################

    @annotate(tag='repo-groups')
    def repo_groups(self):
        """
        Returns number of lines changed per author per day

        :param repo_url: the repository's URL
        """
        repoGroupsSQL = s.sql.text("""
            SELECT *
            FROM repo_groups
        """)
        results = pd.read_sql(repoGroupsSQL, self.db)
        return results

    @annotate(tag='downloaded-repos')
    def downloaded_repos(self):
        """
        Returns all repository names, URLs, and base64 URLs in the facade database
        """
        downloadedReposSQL = s.sql.text("""
            SELECT
                repo.repo_id,
                repo.repo_name,
                repo.description,
                repo.repo_git AS url,
                repo.repo_status,
                a.commits_all_time,
                b.issues_all_time ,
                rg_name
            FROM
                repo
                left outer join
                (select repo_id,    COUNT ( commits.cmt_id ) AS commits_all_time from commits group by repo_id ) a on
                repo.repo_id = a.repo_id
                left outer join
                (select repo_id, count ( issues.issue_id) as issues_all_time from issues  group by repo_id) b
                on
                repo.repo_id = b.repo_id
                JOIN repo_groups ON repo_groups.repo_group_id = repo.repo_group_id
            order by commits_all_time desc
        """)
        results = pd.read_sql(downloadedReposSQL, self.db)
        results['url'] = results['url'].apply(lambda datum: datum.split('//')[1])
        # if self.projects:
        #     results = results[results.project_name.isin(self.projects)]
        if self.projects:
              results = results[results.project_name.isin(self.projects)]

        b64_urls = []
        for i in results.index:
            b64_urls.append(base64.b64encode((results.at[i, 'url']).encode()))
        results['base64_url'] = b64_urls

        return results

    @annotate(tag='repos-in-repo-groups')
    def repos_in_repo_groups(self, repo_group_id):
        """
        Returns a list of all the repos in a repo_group

        :param repo_group_id: The repository's repo_group_id
        """
        repos_in_repo_groups_SQL = s.sql.text("""
            SELECT
                repo.repo_id,
                repo.repo_name,
                repo.description,
                repo.repo_git AS url,
                repo.repo_status,
                a.commits_all_time,
                b.issues_all_time
            FROM
                repo
                left outer join
                (select repo_id, COUNT ( commits.cmt_id ) AS commits_all_time from commits group by repo_id ) a on
                repo.repo_id = a.repo_id
                left outer join
                (select repo_id, count ( issues.issue_id) as issues_all_time from issues  group by repo_id) b
                on
                repo.repo_id = b.repo_id
                JOIN repo_groups ON repo_groups.repo_group_id = repo.repo_group_id
            WHERE
                repo_groups.repo_group_id = :repo_group_id
            ORDER BY commits_all_time DESC
        """)

        results = pd.read_sql(repos_in_repo_groups_SQL, self.db, params={'repo_group_id': repo_group_id})
        return results

    @annotate(tag='get-repo')
    def get_repo(self, owner, repo):
        """
        Returns repo id and repo group id by owner and repo

        :param owner: the owner of the repo
        :param repo: the name of the repo
        """
        getRepoSQL = s.sql.text("""
            SELECT repo.repo_id, repo.repo_group_id, rg_name
            FROM repo JOIN repo_groups ON repo_groups.repo_group_id = repo.repo_group_id
            WHERE repo_name = :repo AND repo_path LIKE :owner
            GROUP BY repo_id, rg_name
        """)

        results = pd.read_sql(getRepoSQL, self.db, params={'owner': '%{}_'.format(owner), 'repo': repo,})

        return results

    # @annotate(tag='dosocs-repos')
    def get_repos_for_dosocs(self):
        """ Returns a list of repos along with their repo_id & path """
        get_repos_for_dosocs_SQL = s.sql.text("""
            SELECT b.repo_id, CONCAT(a.value || b.repo_group_id || chr(47) || b.repo_path || b.repo_name) AS path
            FROM settings a, repo b
            WHERE a.setting='repo_directory'
        """)

        results = pd.read_sql(get_repos_for_dosocs_SQL, self.db)
        return results

    @annotate(tag="get-issues")
    def get_issues(self, repo_group_id, repo_id=None):
        if not repo_id:
            issuesSQL = s.sql.text("""
                SELECT issue_title,
                    issues.issue_id,
                    issues.repo_id,
                    issues.html_url,
                    issue_state                                 AS STATUS,
                    issues.created_at                           AS DATE,
                    count(issue_events.event_id),
                    MAX(issue_events.created_at)                AS LAST_EVENT_DATE,
                    EXTRACT(DAY FROM NOW() - issues.created_at) AS OPEN_DAY
                FROM issues,
                    issue_events
                WHERE issues.repo_id IN (SELECT repo_id FROM repo WHERE repo_group_id = :repo_group_id)
                AND issues.issue_id = issue_events.issue_id
                GROUP BY issues.issue_id
                ORDER by OPEN_DAY DESC
            """)
            results = pd.read_sql(issuesSQL, self.db, params={'repo_group_id': repo_group_id})
            return results
        else:
            issuesSQL = s.sql.text("""
                SELECT issue_title,
                    issues.issue_id,
                    issues.repo_id,
                    issues.html_url,
                    issue_state                                 AS STATUS,
                    issues.created_at                           AS DATE,
                    count(issue_events.event_id),
                    MAX(issue_events.created_at)                AS LAST_EVENT_DATE,
                    EXTRACT(DAY FROM NOW() - issues.created_at) AS OPEN_DAY,
                    repo_name
                FROM issues JOIN repo ON issues.repo_id = repo.repo_id, issue_events
                WHERE issues.repo_id = :repo_id
                AND issues.issue_id = issue_events.issue_id
                GROUP BY issues.issue_id, repo_name
                ORDER by OPEN_DAY DESC
            """)
            results = pd.read_sql(issuesSQL, self.db, params={'repo_id': repo_id})
            return results