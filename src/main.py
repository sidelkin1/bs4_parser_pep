import logging
import re
from collections import Counter
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import (BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL, PEP_LIST_URL,
                       PEP_MAX_LIMIT)
from exceptions import (ParserFindAllVersionsException,
                        ParserStatusAbbreviationException)
from outputs import control_output
from utils import find_tag, get_response


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, features='lxml')

    main_div = find_tag(soup, 'section', id='what-s-new-in-python')
    div_with_ul = find_tag(main_div, 'div', class_='toctree-wrapper')
    sections_by_python = div_with_ul.find_all('li', class_='toctree-l1')

    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)

        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )

    return results


def latest_versions(session):
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', class_='sphinxsidebarwrapper')
    ul_tags = sidebar.find_all('ul')

    search_string = 'All versions'
    for ul in ul_tags:
        if search_string in ul.text:
            a_tags = ul.find_all('a')
            break
        error_msg = f'Текст {ul.text} не содержит строку `{search_string}`'
        logging.error(error_msg, stack_info=True)
        raise ParserFindAllVersionsException(error_msg)

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in tqdm(a_tags):
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )

    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')
    main_tag = find_tag(soup, 'div', role='main')
    table_tag = find_tag(main_tag, 'table', class_='docutils')
    pdf_a4_tag = find_tag(table_tag, 'a', href=re.compile(r'.+pdf-a4\.zip$'))
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)

    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename

    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    response = get_response(session, PEP_LIST_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, features='lxml')
    index = find_tag(soup, 'section', id='numerical-index')
    tbody = find_tag(index, 'tbody')

    pattern = re.compile(r'^/pep-\d{4}')
    pep_count = Counter()
    missmatch_statuses = []
    for row in tqdm(tbody.find_all('tr', limit=PEP_MAX_LIMIT)):
        abbr = find_tag(row, 'abbr')
        link = find_tag(row, 'a', href=pattern)
        pep_url = urljoin(PEP_LIST_URL, link['href'])

        pep_abbr = abbr.text[1:]
        preview_status = EXPECTED_STATUS.get(pep_abbr)
        if preview_status is None:
            error_msg = f'Неизвестное обозначение PEP-статуса: {pep_abbr}'
            logging.error(error_msg, stack_info=True)
            raise ParserStatusAbbreviationException(error_msg)

        response = get_response(session, pep_url)
        if response is None:
            continue

        soup = BeautifulSoup(response.text, features='lxml')
        status_dt = find_tag(
            soup,
            lambda tag: tag.name == 'dt' and tag.text == 'Status:'
        )
        status_dd = status_dt.find_next_sibling('dd')
        pep_status = status_dd.text
        pep_count.update((pep_status,))

        if pep_status not in preview_status:
            missmatch_statuses.append(
                (pep_url, pep_status, preview_status)
            )

    if missmatch_statuses:
        message = 'Несовпадающие статусы:'
        for pep_url, pep_status, preview_status in missmatch_statuses:
            message = '\n'.join((
                message,
                f'{pep_url}',
                f'Статус в карточке: {pep_status}',
                f'Ожидаемые статусы:: {preview_status}',
            ))
        logging.info(message)

    results = [('Статус', 'Количество')]
    total = 0
    for status, count in pep_count.items():
        results.append((status, count))
        total += count
    results.append(('Total', total))
    return results


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')

    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')

    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
