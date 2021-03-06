from fabtools import require, git, python, nginx, supervisor, service, files
from fabric.context_managers import cd, shell_env
from fabric.api import put, run, task, env
from os import environ, path
import time, re


def test_uwsgi_is_started(now):
    testing_file = '/tmp/test_uwsgi.py'
    if files.is_file(testing_file):
        files.remove(testing_file)
    put('files/test_uwsgi.py', testing_file)

    output = run('python {} {} {}'.format(testing_file, env.uwsgi_socket(now), env.server_name))
    assert '"message"' in output


def deploy_nginx_api_site(now):
    files.upload_template('templates/uwsgi.ini',  env.uwsgi_config_path(now),
        context={
           'config_path': env.apitaxi_config_path(now),
           'api_path': env.apitaxi_dir(now),
           'venv_path': env.apitaxi_venv_path(now),
           'uwsgi_file': env.uwsgi_file(now),
           'uwsgi_pid_file': env.uwsgi_pid_file(now),
           'uwsgi_log_dir': env.uwsgi_logdir,
           'uwsgi_launcher_logdir': env.uwsgi_launcher_logdir,
           'socket': env.uwsgi_socket(now),
           'processes': env.wsgi_processes,
           'threads': env.wsgi_threads
       }
    )

    uwsgi = path.join(env.apitaxi_venv_path(now), 'bin', 'uwsgi')
    require.supervisor.process('uwsgi_{}'.format(now),
        command='{} --ini {}'.format(uwsgi, env.uwsgi_config_path(now)),
        directory=env.apitaxi_venv_path(now),
        stdout_logfile = '/var/log/nginx/apitaxi.log',
        user='www-data'
    )

    test_uwsgi_is_started(now)

    require.nginx.site('apitaxi',
        template_source='templates/nginx_site.conf',
        domain_name=getattr(env.conf_api, 'HOST', 'localhost'),
        port=getattr(env.conf_api, 'PORT', 80),
        socket=env.uwsgi_socket(now)
    )

def clean_directories(now):
    l = run('for i in {}/deployment_*; do echo $i; done'.format(env.uwsgi_dir)).split("\n")
    for d in l:
        if not files.is_dir(d):
            continue
        if d == env.deployment_dir(now):
            continue
        files.remove(d, recursive=True)

    l = run('for i in {}/apitaxi_*; do echo $i; done'.format(env.uwsgi_socket_dir)).split("\n")
    for f in l:
        if not files.is_file(f):
            continue
        if f == env.uwsgi_socket(now):
            continue
        files.remove(f)
    #The pid file should be remove when the process stops


def stop_old_processes(now):
    l = run('for i in /etc/supervisor/conf.d/uwsgi_*; do echo $i; done').split("\n")
    for f in l:
        if f == env.deployment_dir:
            continue
        m = re.search(r'([^/]*).conf$', f)
        if not m:
            continue
        process = m.group(1)
        supervisor.stop_process(process)
        files.remove(f, use_sudo=True)


@task
def deploy_api():
    now = int(time.time())
    require.files.directory(env.deployment_dir(now))
    with cd(env.deployment_dir(now)):
        run('wget https://github.com/openmaraude/APITaxi/archive/master.zip')
        run('unzip master.zip')

    with cd(env.apitaxi_dir(now)):
        require.python.virtualenv(env.apitaxi_venv_path(now))
        with python.virtualenv(env.apitaxi_venv_path(now)):
            python.install_pip()
            require.python.package('uwsgi')
            python.install_requirements('requirements.txt')
            put(environ['APITAXI_CONFIG_FILE'], env.apitaxi_config_path(now))
            run('python manage.py db upgrade')
        deploy_nginx_api_site(now)
    if not service.is_running('nginx'):
        service.start('nginx')
    clean_directories(now)
    stop_old_processes(now)
