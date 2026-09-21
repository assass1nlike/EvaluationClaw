"""Install unmodified software hooks once, then publish verified pre_start caches."""
import json
from pathlib import Path
import shlex
import time

import yaml

from local.eval_readiness import check_software, configure_execution_network, deadline, source_digest


def prepare(run, config):
    from gym_anything.api import from_config
    run = Path(run)
    env = from_config(str(run / 'environment'), task_id=config['task'])
    configure_execution_network(env, config['runner'])
    runner = env._runner
    result = {'status': 'preparing', 'started': time.time(), 'source_sha256': source_digest(config['source'])}
    try:
        with deadline(36000):
            runner.start(seed=42)
            # Bound stalled network requests without changing package sources or versions.
            apt_config = 'Acquire::http::Timeout "60";\nAcquire::https::Timeout "60";\nAcquire::Retries "3";\n'
            command = 'printf %s ' + shlex.quote(apt_config) + ' > /etc/apt/apt.conf.d/99-gym-network'
            if runner.exec('bash -lc ' + shlex.quote(command), timeout=30) != 0:
                raise RuntimeError('Could not configure package download timeouts')
            result['apt_network'] = {'timeout_seconds': 60, 'retries': 3}
            hook = env.env_spec.hooks['pre_start']
            command = f'bash -lc {hook} > /home/ga/env_setup_pre_start.log 2>&1'
            result['install_returncode'] = runner.exec(command, timeout=36000)
            if result['install_returncode'] != 0:
                raise RuntimeError('Official software install hook failed')
            # Pull exactly the images declared by the generated software environment.
            compose = Path(config['source']) / 'config/docker-compose.yml'
            images = sorted({s['image'] for s in yaml.safe_load(compose.read_text()).get('services', {}).values() if 'image' in s}) if compose.exists() else []
            images += {'rancher_env': ['rancher/rancher:v2.8.5'],
                       'erpnext_env': ['frappe/erpnext:v15', 'mariadb:10.6', 'redis:6.2-alpine'],
                       'redmine_env': ['redmine:6.0-bookworm', 'postgres:16']}.get(config['env'], [])
            images = sorted(set(images))
            for image in images:
                for attempt in range(4):
                    rc = runner.exec('bash -lc ' + shlex.quote('docker pull ' + shlex.quote(image) + ' >> /home/ga/software_images.log 2>&1'), timeout=1800)
                    if rc == 0:
                        break
                    time.sleep(5)
                if rc:
                    raise RuntimeError(f'Could not prepare declared image: {image}')
            result['declared_images'] = images
            result['check_returncode'] = check_software(runner, env.env_spec.id, installed_only=True)
            if result['check_returncode'] != 0:
                raise RuntimeError('Required software missing after install')
            versions = 'dpkg-query -W > /home/ga/software_packages.tsv'
            if images:
                versions += ' && docker image inspect ' + ' '.join(map(shlex.quote, images)) + ' > /home/ga/software_images.json'
            if runner.exec('bash -lc ' + shlex.quote(versions), timeout=120) != 0:
                raise RuntimeError('Could not record installed software versions')
            runner.copy_from('/home/ga/software_packages.tsv', str(run / 'packages.tsv'))
            if images:
                runner.copy_from('/home/ga/software_images.json', str(run / 'images.json'))
            runner.set_checkpoint_key('pre_start')
            if runner.checkpoint_exists():
                raise RuntimeError('Refusing to overwrite an existing pre_start cache')
            if not runner.create_checkpoint():
                raise RuntimeError('Official checkpoint creation failed')
            result['checkpoint'] = str(runner._get_checkpoint_path()) if config['runner'] == 'qemu' else runner._get_checkpoint_name()
            result['status'] = 'ready'
    except BaseException as error:
        result.update(status='failed', error=type(error).__name__, detail=str(error))
    finally:
        try:
            runner.copy_from('/home/ga/env_setup_pre_start.log', str(run / 'install.log'))
            runner.copy_from('/home/ga/software_images.log', str(run / 'image-pulls.log'))
        except Exception:
            pass
        runner.stop()
        result['finished'] = time.time()
        (run / 'software.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['status'] == 'ready' else 1
