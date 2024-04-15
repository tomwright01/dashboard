.. _glossary:

----------------------
Configuration Glossary
----------------------

Listed below are all configuration values that may be set for the QC dashboard.
They're organized into sections based on the feature that they configure.
These values should be set in your shell (or your uWSGI configuration file).


Cluster
*******
Allows the dashboard to make use of a computing cluster (e.g.
`Slurm <https://slurm.schedmd.com/documentation.html>`_).

Optional
^^^^^^^^
* **DASHBOARD_QSUBMIT_CMD**

  * Description: Tells the dashboard which command to use when submitting
    a job. If the command is not available on your PATH, you should provide
    the full path (e.g. /usr/bin/sbatch instead of sbatch).
  * Default value: ``sbatch``
* **DASHBOARD_QSUBMIT_OPTIONS**

  * Description: Options to use when submitting each queue job. This is the
    ideal place to set things like a default working directory or QoS.
  * Default value: ``--chdir=/tmp/``
* **DASHBOARD_QSUBMIT_SCRIPTS**

  * Description: The path to a folder that will hold all of the scripts the
    dashboard may submit to the queue. If unset, the dashboard will search for
    a folder named "queue_jobs" inside the folder where its code resides.
  * Default value: ``../dashboard/queue_jobs``

Example
^^^^^^^
.. code-block:: bash

  # Using a non-standard submit command location
  export DASHBOARD_QSUBMIT_CMD=/home/user1/sbatch

  # Override the working directory + add a QoS
  export DASHBOARD_QSUBMIT_OPTIONS=--qos=dashboard --chdir=/home/user1/

  # Set a location for submit scripts
  export DASHBOARD_QSUBMIT_SCRIPTS=/home/user1/job_scripts

Database
********
Configure the database backend for the dashboard.

Required
^^^^^^^^
* **POSTGRES_PASS**

  * Description: The password to use when connecting to the database. Can be
    left unset ONLY if a password-less authentication method like identd has
    been configured for the database.

Optional
^^^^^^^^
* **POSTGRES_DATABASE**

  * Description: The name of the database to connect to.
  * Default value: ``dashboard``
* **POSTGRES_TEST_DATABASE**

  * Description: The name of the database to create / delete when running tests.
  * Default value: ``test_dashboard``
* **POSTGRES_SRVR**

  * Description: The postgres server to connect to. May be a fully qualified
    domain name or an IP address.
  * Default value: ``localhost``
* **POSTGRES_USER**

  * Description: The username to use when connecting to the database.
  * Default value: The username that the dashboard runs under.
* **POSTGRES_PORT**

  * Description: The port to use when connecting to the database.
  * Default value: ``5432``
* **TIMEZONE**

  * Description: The time zone to use when storing timestamps. Note that this
    should be represented as the number of minutes east of UTC. For example,
    Eastern Daylight Time is 240 minutes behind UTC so it would be represented
    as -240.
  * Default value: ``-240``. This is equivalent to EDT.

Example
^^^^^^^
.. code-block:: bash

    export POSTGRES_USER=dashboard_user
    export POSTGRES_PASS=somepassword
    export POSTGRES_SRVR=127.0.0.1
    export POSTGRES_DATABASE=mydatabasename
    # -300 == central time
    export TIMEZONE=-300

Email
*****
These settings configure email functionality for the dashboard. When configured
correctly, they enable the dashboard to send email notifications to
administrators and scheduled reminders to users.

Optional
^^^^^^^^
* **ADMINS**

  * Description: A comma separated list of dashboard administrator emails.
    These emails will be notified in case of code exceptions and may be sent
    reminder emails when QC reminders are enabled. If unset, no administrator
    emails will be sent.
  * Default value: ``None``

* **DASHBOARD_MAIL_SERVER**

  * Description: The server that will handle outgoing email. To turn off
    emails set this to 'disabled'.
  * Default value: ``'smtp.gmail.com'``

* **DASHBOARD_MAIL_PORT**

  * Description: The port on DASHBOARD_MAIL_SERVER to use.
  * Default value: ``465``

* **DASHBOARD_MAIL_UNAME**

  * Description: The username to use when connecting to DASHBOARD_MAIL_SERVER.
    If authentication is not required it can be left unset. The 'sender' field
    for all emails originating from the dashboard will be set to this value
    if DASHBOARD_SUPPORT_EMAIL is left unset. If this is left unset as well,
    the sender will appear as 'no-reply@kimellab.ca'.
  * Default value: ``None``

* **DASHBOARD_MAIL_PASS**

  * Description: The password to use when connecting to DASHBOARD_MAIL_SERVER.
    If authentication is not required it can be left unset.
  * Default value: ``None``

* **DASHBOARD_SUPPORT_EMAIL**

  * Description: The email address to send user support requests to. If set,
    this address will also appear as the sender for any email that originates
    from the dashboard.
  * Default value: ``DASHBOARD_MAIL_UNAME@DASHBOARD_MAIL_SERVER``

* **DASHBOARD_MAIL_SSL**

  * Description: Whether to use SSL when sending email. For certain mail
    servers, such as Gmail's server, it must be true for email to be forwarded.
  * Default value: ``True``

* **DASH_LOG_MAIL_SERVER**

  * Description: The server to email logs to. Log emails may be turned off by
    setting this to 'disabled'.
  * Default value: ``smtp.camh.net``

* **DASH_LOG_MAIL_PORT**

  * Description: The port on DASH_LOG_MAIL_SERVER to forward emails to.
  * Default value: ``25``

* **DASH_LOG_MAIL_USER**

  * Description: The username to use when for authentication on
    DASH_LOG_MAIL_SERVER. Can be left unset if authentication is not required
    by the server.
  * Default value: ``None``

* **DASH_LOG_MAIL_PASS**

  * Description: The password to use for authentication on DASH_LOG_MAIL_SERVER.
    Can be left unset if authentication is not required by the server.
  * Default value: ``None``

Example
^^^^^^^
.. code-block:: bash

    # Configure logs to be sent to email.
    export DASH_LOG_MAIL_SERVER=myemailserver.ca
    export DASH_LOG_MAIL_USER=myuser
    export DASH_LOG_MAIL_PASS=myuserspassword
    # Use when the mail server uses a non-standard smtp port
    export DASHBOARD_MAIL_PORT=8888

    # Configure email notifications
    export DASHBOARD_MAIL_SERVER=myotheremailserver.ca
    export DASH_LOG_MAIL_USER=myotheruser
    export DASH_LOG_MAIL_PASS=myotherpassword

    # Configure recipient of support requests
    export DASHBOARD_SUPPORT_EMAIL=support@myemailserver.ca

    # Configure administrator emails for notifications
    export ADMINS=admin1@gmail.ca,admin2@outlook.com,admin3@myemailserver.ca

Logging
*******
Configure the amount and type of logging that the dashboard does.

Optional
^^^^^^^^
* **DASH_LOG_LEVEL**

  * Description: Set the log level for all loggers that the dashboard uses.
  * Accepted values: DEBUG, INFO, WARNING, ERROR, CRITICAL.
  * Default value: ``DEBUG``

* **DASHBOARD_LOG_SERVER**

  * Description: The fully qualified domain name or IP address of a server
    that is running `datman's log server <http://imaging-genetics.camh.ca/datman/>`_.
    All log messages will also be sent to the log server, if one is provided.
  * Default value: ``None``

* **DASHBOARD_LOG_SERVER_PORT**

  * Description: The port that DASHBOARD_LOG_SERVER is listening on. This
    setting is not read if DASHBOARD_LOG_SERVER is not defined.
  * Default value: ``9020``

* **DASH_LOG_DIR**

  * Description: The directory to store log files in. Log files will only be
    written when the dashboard is running in development mode with FLASK_DEBUG
    set. The destination folder must be writable for the user that the
    dashboard runs under.
  * Default value: a folder named 'logs' with the dashboard's base directory.

Example
^^^^^^^
.. code-block:: bash

  # Turn down logging
  export DASH_LOG_LEVEL=ERROR

  # Log to datman's log server
  export DASHBOARD_LOG_SERVER=mylogserver.ca
  # using a non-standard port
  export DASHBOARD_LOG_SERVER_PORT=7777

  # Tell the dashboard where to store file logs, if it's using them
  export DASH_LOG_DIR=/var/log/dashboard

Menu Configuration
******************
These settings allow the user to add items to the dashboard's menus.

Optional
^^^^^^^^
* **DASH_MENU_CONFIG**

  * Description: The full path to a yaml file defining buttons to add to
    the dashboard's configurable menus. See :ref:`here <menu_config>` for
    information on how to create this file.

User Authentication
*******************
These settings are used to configure user authentication by OAuth. Note that at
least one of these authentication methods MUST be configured, unless the
dashboard is running in development mode.

Required
^^^^^^^^
* GitHub configuration. You can see GitHub's instructions for acquiring a
  client ID and secret `here <https://docs.github.com/en/developers/apps/building-oauth-apps/creating-an-oauth-app>`_

  * **OAUTH_CLIENT_GITHUB**

    * Description: The OAuth client value provided by GitHub.
  * **OAUTH_SECRET_GITHUB**

    * Description: The OAuth secret value provided by GitHub.

* GitLab configuration

  * **OAUTH_CLIENT_GITLAB**

    * Description: The OAuth client value provided by GitLab.

  * **OAUTH_SECRET_GITLAB**

    * Description: The OAuth secret value provided by GitLab.

General Application Configuration
*********************************
Required
^^^^^^^^
* **FLASK_SECRET_KEY**

  * Description: A secret value that must be provided before startup to allow
    the dashboard to encrypt session information and cookies. This value
    should be hard to guess and kept as secret as possible.

Optional
^^^^^^^^
* **FLASK_ENV**

  * Description: Tells Flask what type of environment it is running within.
    Switching to 'development' mode can enable extensions to help with testing
    and development. Do not use 'development' mode on a production server.
  * Accepted values: ``'production'`` or ``'development'``
  * Default value: ``'production'``
* **FLASK_DEBUG**

  * Description: Tells Flask and its plugins to run in debug mode. Setting
    'FLASK_ENV' to development mode automatically turns on FLASK_DEBUG.
    `See here for more info <https://flask.palletsprojects.com/en/3.0.x/config/#DEBUG>`_
  * Accepted values: ``True`` (if it should run in debug mode) or ``False``
  * Default value: ``False``
* **LOGIN_DISABLED**

  * Description: Whether to turn off OAuth authentication and allow access
    without logging in. Do not set this to True on a production instance.
  * Accepted values: ``True`` (if it should be disabled) or ``False``
  * Default value: ``False``

Github Issues
*************
Allow the dashboard to automatically create and display Github issues.

Required
^^^^^^^^

Optional
^^^^^^^^
* **GITHUB_REPO**

  * Description: The name of the repository that will host the user-reported
    data issues created through the dashboard.
* **GITHUB_ISSUES_OWNER**

  * Description: The user that owns the GITHUB_REPO repository.

* **GITHUB_ISSUES_PUBLIC**

  * Description: Indicates whether the GITHUB_REPO repository is public (True)
    or private (False)
  * Default value: ``True``

Example
^^^^^^^
.. code-block:: bash

   export GITHUB_ISSUES_OWNER=TIGRLab
   # Issues that are made will be added to the 'Admin' repo
   export GITHUB_REPO=Admin
   # Set to False to indicate the Admin repository is private
   export GITHUB_ISSUES_PUBLIC=False

Scheduler
*********
Configuration for the dashboard's job scheduler.

* **DASHBOARD_SCHEDULER**

  * Description: Indicates whether to start (True) the dashboard scheduler
    or not (False). Note that if the dashboard is just being imported
    by another python app, the scheduler should NOT be started up or errors and
    unexpected behavior will occur.
  * Accepted values: ``True`` or ``False``
  * Default value: ``False``
* **DASHBOARD_SCHEDULER_API**

  * Description: Controls whether remote job submission will be enabled (True)
    or disabled (False). Note that remote job submission occurs over HTTP,
    so private information should never be bundled within jobs if they are
    being sent over a non-private network.
  * Accepted values: ``True`` or ``False``
  * Default value: ``False``
* **DASHBOARD_SCHEDULER_USER**

  * Description: The username to use when submitting jobs to the scheduler.
    Clients submitting jobs will need to provide the same user as the
    instance of the dashboard receiving jobs.
* **DASHBOARD_SCHEDULER_PASS**

  * Description: The password to use when submitting jobs to the scheduler.
    Clients submitting jobs will need to provide the same password that
    has been set by the instance of the dashboard that is receiving jobs.
* **DASHBOARD_URL**

  * Description: The URL to send scheduler jobs to. This setting is needed
    only by 'client' instances of the dashboard.

Run Log Reporting
*****************
Configures whether to display nightly pipeline run logs. If nightly scripts
are run for a study's data, the base directory where logs are stored can be
provided to ensure the most recent run log is displayed on the study's landing
page. Note that the most recent log for each study should be named
``STUDY_latest.log``, where STUDY is the name datman recognizes the study by.

Required
^^^^^^^^

Optional
^^^^^^^^
* **DATMAN_RUN_LOGS**

  * Description: The directory to read recent nightly run logs from. If
    left unset run log reporting will be turned off. Log files in this
    directory should be named ``STUDY_latest.log``, where study is
    the datman nickname.
* **DATMAN_RUN_LOGS_DONE**

  * Description: The pattern to search for in the log to identify whether
    or not the nightly run has finished.
  * Default value: ``: Done.``
* **DATMAN_RUN_LOGS_ERROR**

  * Description: The pattern to use to identify log lines that contain errors.
    Used to construct a count of the number of errors in the log, which is
    then displayed in the summary line of the log display.
  * Default value: ``- ERROR -``

XNAT
****
Enable or disable the XNAT integration. Note that if you enable XNAT
configuration, you must ensure you have added the XNAT server settings to the
study_sites table of the database.

A username and password to use when logging in may be set directly in the
dashboard, or may be configured individually for each study in the study config
file. For more information see Datman's configuration guide.

Optional
^^^^^^^^

* **DASH_ENABLE_XNAT**

  * Description: Controls whether XNAT features will be used.
  * Accepted values: ``True`` or ``False``
  * Default values: ``False``
* **XNAT_USER**

  * Description: May be used to provide an XNAT username if one is not set
    in the configuration files. If this is set, XNAT_PASS must be as well.
* **XNAT_PASS**

  * Description: May be used to provide an XNAT password if one is not set
    through the configuration files. If this is set, XNAT_USER must be as well.
