"""External deployment checks and observation of official initialization."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shlex
import signal
import time
from unittest.mock import patch

# These are software prerequisites, not tests of the desired task solution.
INSTALL_CHECKS = {
    'erpnext_env': 'command -v docker && command -v docker-compose && docker image inspect frappe/erpnext:v15 mariadb:10.6 redis:6.2-alpine',
    'libreoffice_writer_env': 'command -v libreoffice && python3 -c "import docx,odf"',
    'moodle_env': 'test -f /var/www/html/moodle/version.php && command -v php && command -v apache2 && python3 -c "import pymysql"',
    'nuxeo_platform_env': 'command -v docker && command -v docker-compose && python3 -c "import requests"',
    'qgis_env': 'command -v qgis && /usr/bin/python3 -c "from qgis.core import QgsApplication"',
    'rancher_env': 'command -v docker && docker image inspect rancher/rancher:v2.8.5',
    'redmine_env': 'command -v docker && docker compose version && docker image inspect redmine:6.0-bookworm postgres:16',
    'rstudio_env': "command -v rstudio && command -v Rscript && Rscript -e 'library(ggplot2)'",
    'vscode_env': 'command -v code && command -v git && command -v node && command -v npm && command -v javac && python3 -c "import pytest"',
    'wordpress_env': 'test -f /var/www/html/wordpress/wp-includes/version.php && command -v wp && command -v php && python3 -c "import pymysql"',
}

SOFTWARE_CHECKS = {
    'moodle_env': "sudo -u www-data php -r 'define(\"CLI_SCRIPT\", true); require \"/var/www/html/moodle/config.php\"; exit($DB->count_records(\"course\") >= 1 ? 0 : 1);'",
    'wordpress_env': 'test -s /var/www/html/wordpress/wp-config.php && wp --allow-root --path=/var/www/html/wordpress core is-installed',
    'redmine_env': 'curl --fail-with-body --silent --show-error --max-time 20 http://localhost:3000/login && test -s /tmp/redmine_seed_result.json',
    'nuxeo_platform_env': 'curl --fail-with-body --silent --show-error --max-time 20 http://localhost:8080/nuxeo/login.jsp',
    'erpnext_env': 'curl --fail-with-body --silent --show-error --max-time 20 http://localhost:8080/api/method/ping',
    'rancher_env': 'curl --fail-with-body --silent --show-error --insecure --max-time 20 https://localhost/ping',
}


def configure_execution_network(env, runner_kind):
    proxy = 'http://10.0.2.2:17891' if runner_kind == 'qemu' else 'http://10.253.240.1:17891'
    direct = ('localhost,127.0.0.1,::1,archive.ubuntu.com,security.ubuntu.com,'
              '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc,.cluster.local,'
              'db,redis-cache,redis-queue,backend,frontend,websocket')
    env.env_spec.security.resolved_env.update({
        'http_proxy': proxy, 'https_proxy': proxy, 'HTTP_PROXY': proxy, 'HTTPS_PROXY': proxy,
        'no_proxy': direct, 'NO_PROXY': direct,
    })


def configure_container_proxy(env):
    if env.env_spec.id.split('@', 1)[0] not in {'erpnext_env', 'nuxeo_platform_env', 'rancher_env', 'redmine_env'}:
        return
    network = env.env_spec.security.resolved_env
    proxy = dict(httpProxy=network['http_proxy'], httpsProxy=network['https_proxy'], noProxy=network['no_proxy'])
    # Docker CLI configuration passes the proxy to containers created by original hooks.
    script = """import json, os, pathlib, pwd
proxy = %r
for name in ('root', 'ga'):
    user = pwd.getpwnam(name)
    directory = pathlib.Path(user.pw_dir) / '.docker'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / 'config.json'
    config = json.loads(path.read_text()) if path.exists() else {}
    config.setdefault('proxies', {})['default'] = proxy
    path.write_text(json.dumps(config) + '\\n')
    path.chmod(0o600)
    os.chown(directory, user.pw_uid, user.pw_gid)
    os.chown(path, user.pw_uid, user.pw_gid)
""" % proxy
    if env._runner.exec('python3 -c ' + shlex.quote(script), timeout=30) != 0:
        raise SetupAbort('Could not configure guest Docker container proxy')


class SetupAbort(BaseException):
    """Cross official exception suppression; converted to RuntimeError at reset."""


@contextmanager
def deadline(seconds):
    previous = signal.getsignal(signal.SIGALRM)
    remaining, interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expired(*_):
        raise SetupAbort('initialization deadline exceeded')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, remaining) if remaining else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if remaining:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, remaining - (time.monotonic() - started)), interval)


def source_digest(source):
    source = Path(source)
    digest = hashlib.sha256()
    for path in sorted(source.rglob('*')):
        rel = path.relative_to(source)
        if path.is_file() and rel.parts[0] in {'env.json', 'scripts', 'config', 'utils'} and '__pycache__' not in rel.parts:
            digest.update(str(rel).encode())
            digest.update(path.read_bytes())
            digest.update(str(path.stat().st_mode & 0o111).encode())
    return digest.hexdigest()


def check_software(runner, env_id, *, installed_only=False):
    env_id = env_id.split('@', 1)[0]
    check = INSTALL_CHECKS[env_id]
    if not installed_only and env_id in SOFTWARE_CHECKS:
        check += ' && ' + SOFTWARE_CHECKS[env_id]
    return runner.exec('bash -lc ' + shlex.quote('(' + check + ') > /home/ga/software_readiness.log 2>&1'), timeout=90)


@contextmanager
def observe_prepared_initialization(env, run):
    """Preserve official hook failure handling while recording setup evidence."""
    run = Path(run)
    original_reset, execute = env.reset, env._runner.exec
    commands = {}
    for stage, logfile in [('pre_start', 'env_setup_pre_start'), ('post_start', 'env_setup_post_start')]:
        hook = env.env_spec.hooks.get(stage)
        if hook:
            commands[f'bash -lc {hook} > /home/ga/{logfile}.log 2>&1'] = stage
    if env.task_spec and env.task_spec.hooks and env.task_spec.hooks.pre_task:
        commands[f'bash -lc {env.task_spec.hooks.pre_task} > /home/ga/task_pre_task.log 2>&1'] = 'pre_task'
    state = {'status': 'initializing', 'stage': 'runtime', 'events': [],
             'failure_policy': 'official'}

    def save():
        (run / 'readiness.json').write_text(json.dumps(state, indent=2) + '\n')

    def checked_exec(command, *args, **kwargs):
        stage = commands.get(command)
        if not stage:
            return execute(command, *args, **kwargs)
        state['stage'] = stage
        save()
        event = {'stage': stage, 'started': time.time()}
        try:
            if stage == 'post_start':
                configure_container_proxy(env)
            result = execute(command, *args, **kwargs)
            event['returncode'] = result
            if stage == 'post_start' and result == 0:
                if env.env_spec.id.split('@', 1)[0] == 'erpnext_env':
                    reloaded = execute('docker exec erpnext_frontend_1 nginx -s reload', timeout=30)
                    event['frontend_reload_returncode'] = reloaded
                    if reloaded != 0:
                        raise SetupAbort('ERPNext frontend reload failed')
                try:
                    event['software_check_returncode'] = check_software(env._runner, env.env_spec.id)
                except Exception as error:
                    event['software_check_error'] = type(error).__name__
            return result
        except BaseException as error:
            event['error'] = type(error).__name__
            raise
        finally:
            event['elapsed_seconds'] = time.time() - event['started']
            state['events'].append(event)
            save()

    def reset(*args, **kwargs):
        state.update(status='initializing', stage='runtime')
        save()
        try:
            env._runner.set_checkpoint_key('pre_start')
            if not env._runner.checkpoint_exists():
                raise SetupAbort('verified software checkpoint missing')
            with patch.object(env._runner, 'exec', checked_exec):
                observation = original_reset(*args, **kwargs)
            issues = [event for event in state['events'] if event.get('error')
                      or event.get('returncode') not in (None, 0)
                      or event.get('software_check_returncode') not in (None, 0)
                      or event.get('software_check_error')]
            state.update(status='ready', stage='ready', finished=time.time(),
                         initialization_issues=issues)
            save()
            return observation
        except SetupAbort as error:
            env._reset_complete = False
            state.update(status='failed', error=type(error).__name__, detail=str(error), finished=time.time())
            save()
            raise RuntimeError('Local deployment failed; see readiness.json') from error
        except Exception as error:
            state.update(status='failed', error=type(error).__name__, detail=str(error), finished=time.time())
            save()
            raise
        finally:
            directory = run / 'initialization'
            directory.mkdir(exist_ok=True)
            copied = {}
            for name in ('env_setup_pre_start.log', 'env_setup_post_start.log', 'task_pre_task.log', 'software_readiness.log'):
                try:
                    env._runner.copy_from('/home/ga/' + name, str(directory / name))
                    copied[name] = (directory / name).exists()
                except Exception as error:
                    copied[name] = type(error).__name__
            (directory / 'logs.json').write_text(json.dumps(copied, indent=2) + '\n')

    with patch.object(env, 'reset', reset):
        yield env
