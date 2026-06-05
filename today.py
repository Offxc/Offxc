import datetime
from dateutil import relativedelta
import requests
import os
from lxml import etree
import time
import hashlib

# Fine-grained personal access token with All Repositories access:
# Account permissions: read:Followers, read:Starring, read:Watching
# Repository permissions: read:Commit statuses, read:Contents, read:Issues, read:Metadata, read:Pull Requests
# Issues and pull requests permissions not needed at the moment, but may be used in the future
TOKEN_CANDIDATES = []
# In CI we must prefer the user's ACCESS_TOKEN exclusively when present.
# Falling back to GITHUB_TOKEN can silently undercount profile stats.
if os.environ.get('ACCESS_TOKEN'):
    TOKEN_CANDIDATES = [os.environ['ACCESS_TOKEN']]
elif os.environ.get('GITHUB_TOKEN'):
    TOKEN_CANDIDATES = [os.environ['GITHUB_TOKEN']]
if not TOKEN_CANDIDATES:
    raise EnvironmentError('Set ACCESS_TOKEN or GITHUB_TOKEN before running today.py')
ACTIVE_TOKEN_INDEX = 0
HEADERS = {'authorization': 'token ' + TOKEN_CANDIDATES[ACTIVE_TOKEN_INDEX]}
USER_NAME = os.environ['USER_NAME'] # e.g. 'Offxc'
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'graph_commits': 0, 'loc_query': 0, 'graph_languages': 0, 'graph_streak': 0}

SVG_NS = 'http://www.w3.org/2000/svg'

def svg_tag(tag):
    """Return a namespaced SVG tag for lxml element creation."""
    return f'{{{SVG_NS}}}{tag}'

# Official GitHub/Linguist language colours (github.com/ozh/github-colors)
LANGUAGE_COLORS = {
    'TypeScript': '#3178c6', 'JavaScript': '#f1e05a', 'Python': '#3572a5',
    'Java': '#b07219', 'Shell': '#89e051', 'HTML': '#e34c26', 'CSS': '#563d7c',
    'C': '#555555', 'C++': '#f34b7d', 'C#': '#178600', 'Go': '#00add8',
    'Rust': '#dea584', 'Ruby': '#701516', 'PHP': '#4f5d95', 'Kotlin': '#a97bff',
    'Swift': '#f05138', 'Dart': '#00b4ab', 'Lua': '#000080', 'Vue': '#41b883',
    'Dockerfile': '#384d54', 'Makefile': '#427819', 'PowerShell': '#012456',
    'SCSS': '#c6538c', 'Svelte': '#ff3e00', 'Astro': '#ff5a03', 'Nix': '#7e7eff',
    'Jupyter Notebook': '#da5b0b', 'TeX': '#3d6117', 'Haskell': '#5e5086',
}
DEFAULT_LANG_COLOR = '#8b949e'
LANG_ROW_Y = [150, 168, 186, 204, 222, 240]
STREAK_ROW_Y = {'current': 311, 'longest': 329}
BAR_CELLS = 16
STATIC_ROW_TARGET_WIDTH = 64
STATIC_FIELD_PREFIX_WIDTHS = {
    'os_data': 5,          # ". OS:"
    'age_data': 9,         # ". Uptime:"
    'host_data': 7,        # ". Host:"
    'kernel_data': 9,      # ". Kernel:"
    'ide_data': 6,         # ". IDE:"
    'lang_prog_data': 24,  # ". Languages.Programming:"
    'lang_comp_data': 21,  # ". Languages.Computer:"
    'lang_real_data': 17,  # ". Languages.Real:"
    'hobby_soft_data': 19, # ". Hobbies.Software:"
    'hobby_hard_data': 19, # ". Hobbies.Hardware:"
    'work_email_data': 9,  # ". Signal:"
    'discord_data': 10     # ". Discord:"
}

def daily_readme(birthday):
    """
    Returns the length of time since I was born
    e.g. 'XX years, XX months, XX days'
    """
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years), 
        diff.months, 'month' + format_plural(diff.months), 
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')


def format_plural(unit):
    """
    Returns a properly formatted number
    e.g.
    'day' + format_plural(diff.days) == 5
    >>> '5 days'
    'day' + format_plural(diff.days) == 1
    >>> '1 day'
    """
    return 's' if unit != 1 else ''


def simple_request(func_name, query, variables):
    """
    Returns a request, or raises an Exception if the response does not succeed.
    """
    global ACTIVE_TOKEN_INDEX, HEADERS
    last_status = None
    last_text = ''
    for index in range(len(TOKEN_CANDIDATES)):
        if index != ACTIVE_TOKEN_INDEX:
            ACTIVE_TOKEN_INDEX = index
            HEADERS = {'authorization': 'token ' + TOKEN_CANDIDATES[ACTIVE_TOKEN_INDEX]}
        request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables':variables}, headers=HEADERS)
        last_status = request.status_code
        last_text = request.text
        if request.status_code == 200:
            body = request.json()
            if 'errors' in body and body['errors']:
                # Try next token if available; otherwise raise with full GraphQL errors.
                continue
            return request
    raise Exception(func_name, ' has failed with a', last_status, last_text, QUERY_COUNT)


def graph_commits(start_date, end_date):
    """
    Uses GitHub's GraphQL v4 API to return total commit contributions
    for the requested date range, aligned with GitHub profile contribution logic.
    """
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                totalCommitContributions
            }
        }
    }'''
    variables = {'start_date': start_date,'end_date': end_date, 'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()['data']['user']['contributionsCollection']['totalCommitContributions'])


def graph_commits_lifetime(start_year):
    """
    Sums commit contributions from account creation year through current year.
    """
    total = 0
    current_year = datetime.datetime.utcnow().year
    for year in range(start_year, current_year + 1):
        start = f'{year}-01-01T00:00:00Z'
        end = f'{year}-12-31T23:59:59Z'
        total += graph_commits(start, end)
    return total


def graph_total_contributions_last_year():
    """
    Returns total profile contributions in the last 1 year window
    (commits + PRs + issues + reviews), matching the profile graph headline.
    """
    query_count('graph_commits')
    query = '''
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    request = simple_request(graph_total_contributions_last_year.__name__, query, {'login': USER_NAME})
    return int(request.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])


def graph_repos_stars(count_type, owner_affiliation, cursor=None, add_loc=0, del_loc=0):
    """
    Uses GitHub's GraphQL v4 API to return my total repository, star, or lines of code count.
    """
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if request.status_code == 200:
        if count_type == 'repos':
            return request.json()['data']['user']['repositories']['totalCount']
        elif count_type == 'stars':
            return stars_counter(request.json()['data']['user']['repositories']['edges'])


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """
    Uses GitHub's GraphQL v4 API and cursor pagination to fetch 100 commits from a repository at a time
    """
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables':variables}, headers=HEADERS) # I cannot use simple_request(), because I want to save the file before raising Exception
    if request.status_code == 200:
        if request.json()['data']['repository']['defaultBranchRef'] != None: # Only count commits if repo isn't empty
            return loc_counter_one_repo(owner, repo_name, data, cache_comment, request.json()['data']['repository']['defaultBranchRef']['target']['history'], addition_total, deletion_total, my_commits)
        else: return 0
    force_close_file(data, cache_comment) # saves what is currently in the file before this program crashes
    if request.status_code == 403:
        raise Exception('Too many requests in a short amount of time!\nYou\'ve hit the non-documented anti-abuse limit!')
    raise Exception('recursive_loc() has failed with a', request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    """
    Recursively call recursive_loc (since GraphQL can only search 100 commits at a time) 
    only adds the LOC value of commits authored by me
    """
    for node in history['edges']:
        author = node['node'].get('author')
        author_user = author.get('user') if isinstance(author, dict) else None
        if author_user == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']:
        return addition_total, deletion_total, my_commits
    else: return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=[]):
    """
    Uses GitHub's GraphQL v4 API to query all the repositories I have access to (with respect to owner_affiliation)
    Queries 60 repos at a time, because larger queries give a 502 timeout error and smaller queries send too many
    requests and also give a 502 error.
    Returns the total number of lines of code in all repositories
    """
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(loc_query.__name__, query, variables)
    if request.json()['data']['user']['repositories']['pageInfo']['hasNextPage']:   # If repository data has another page
        edges += request.json()['data']['user']['repositories']['edges']            # Add on to the LoC count
        return loc_query(owner_affiliation, comment_size, force_cache, request.json()['data']['user']['repositories']['pageInfo']['endCursor'], edges)
    else:
        return cache_builder(edges + request.json()['data']['user']['repositories']['edges'], comment_size, force_cache)


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    """
    Checks each repository in edges to see if it has been updated since the last time it was cached
    If it has, run recursive_loc on that repository to update the LOC count
    """
    cached = True # Assume all repositories are cached
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt' # Create a unique filename for each user
    try:
        with open(filename, 'r') as f:
            data = f.readlines()
    except FileNotFoundError: # If the cache file doesn't exist, create it
        data = []
        if comment_size > 0:
            for _ in range(comment_size): data.append('This line is a comment block. Write whatever you want here.\n')
        with open(filename, 'w') as f:
            f.writelines(data)

    if len(data)-comment_size != len(edges) or force_cache: # If the number of repos has changed, or force_cache is True
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f:
            data = f.readlines()

    cache_comment = data[:comment_size] # save the comment block
    data = data[comment_size:] # remove those lines
    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]['node']['nameWithOwner'].encode('utf-8')).hexdigest():
            try:
                if int(commit_count) != edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']:
                    # if commit count has changed, update loc for that repo
                    owner, repo_name = edges[index]['node']['nameWithOwner'].split('/')
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = repo_hash + ' ' + str(edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']) + ' ' + str(loc[2]) + ' ' + str(loc[0]) + ' ' + str(loc[1]) + '\n'
            except TypeError: # If the repo is empty
                data[index] = repo_hash + ' 0 0 0 0\n'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges, filename, comment_size):
    """
    Wipes the cache file
    This is called when the number of repositories changes or when the file is first created
    """
    with open(filename, 'r') as f:
        data = []
        if comment_size > 0:
            data = f.readlines()[:comment_size] # only save the comment
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')


def add_archive():
    """
    Several repositories I have contributed to have since been deleted.
    This function adds them using their last known data
    """
    with open('cache/repository_archive.txt', 'r') as f:
        data = f.readlines()
    old_data = data
    data = data[7:len(data)-3] # remove the comment block    
    added_loc, deleted_loc, added_commits = 0, 0, 0
    contributed_repos = len(data)
    for line in data:
        repo_hash, total_commits, my_commits, *loc = line.split()
        added_loc += int(loc[0])
        deleted_loc += int(loc[1])
        if (my_commits.isdigit()): added_commits += int(my_commits)
    added_commits += int(old_data[-1].split()[4][:-1])
    return [added_loc, deleted_loc, added_loc - deleted_loc, added_commits, contributed_repos]

def force_close_file(data, cache_comment):
    """
    Forces the file to close, preserving whatever data was written to it
    This is needed because if this function is called, the program would've crashed before the file is properly saved and closed
    """
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print('There was an error while writing to the cache file. The file,', filename, 'has had the partial data saved and closed.')


def stars_counter(data):
    """
    Count total stars in repositories owned by me
    """
    total_stars = 0
    for node in data: total_stars += node['node']['stargazers']['totalCount']
    return total_stars


def graph_languages():
    """
    Uses GitHub's GraphQL v4 API to aggregate language byte counts across all
    repositories I own, returning a {language_name: total_bytes} dict.
    """
    totals = {}
    cursor = None
    while True:
        query_count('graph_languages')
        query = '''
        query ($login: String!, $cursor: String) {
            user(login: $login) {
                repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER], isFork: false) {
                    edges {
                        node {
                            ... on Repository {
                                languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
                                    edges { size node { name } }
                                }
                            }
                        }
                    }
                    pageInfo { endCursor hasNextPage }
                }
            }
        }'''
        request = simple_request(graph_languages.__name__, query, {'login': USER_NAME, 'cursor': cursor})
        repos = request.json()['data']['user']['repositories']
        for edge in repos['edges']:
            languages = edge['node'].get('languages')
            if not languages:
                continue
            for lang_edge in languages['edges']:
                name = lang_edge['node']['name']
                totals[name] = totals.get(name, 0) + lang_edge['size']
        if repos['pageInfo']['hasNextPage']:
            cursor = repos['pageInfo']['endCursor']
        else:
            break
    return totals


def language_breakdown(top_n=6):
    """
    Returns a list of (name, percentage, colour) for the top languages,
    collapsing the remainder into a single 'Other' row.
    """
    totals = graph_languages()
    grand_total = sum(totals.values()) or 1
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    rows = []
    for name, size in ordered[:top_n - 1]:
        rows.append((name, size / grand_total * 100, LANGUAGE_COLORS.get(name, DEFAULT_LANG_COLOR)))
    remainder = ordered[top_n - 1:]
    if remainder:
        other = sum(size for _, size in remainder)
        rows.append(('Other', other / grand_total * 100, DEFAULT_LANG_COLOR))
    return rows


def make_bar(percentage, cells=BAR_CELLS):
    """Build a bracketed block-character bar, e.g. [████████░░░░░░░░]."""
    filled = max(0, min(cells, round(percentage / 100 * cells)))
    return '[' + ('█' * filled) + ('░' * (cells - filled)) + ']'


def make_streak_bar(value, denominator, cells=BAR_CELLS):
    """Build an unbracketed block-character bar relative to a denominator."""
    denominator = denominator or 1
    filled = max(0, min(cells, round(value / denominator * cells)))
    return ('█' * filled) + ('░' * (cells - filled))


def get_streaks():
    """
    Walks the full contribution calendar (account creation year -> now) and
    returns (current_streak, longest_streak) in days.
    """
    query_count('graph_streak')
    years_query = '''
    query ($login: String!) {
        user(login: $login) { contributionsCollection { contributionYears } }
    }'''
    years_request = simple_request('get_streaks_years', years_query, {'login': USER_NAME})
    years = years_request.json()['data']['user']['contributionsCollection']['contributionYears']

    day_counts = {}
    for year in years:
        query_count('graph_streak')
        cal_query = '''
        query ($login: String!, $from: DateTime!, $to: DateTime!) {
            user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                    contributionCalendar {
                        weeks { contributionDays { date contributionCount } }
                    }
                }
            }
        }'''
        variables = {'login': USER_NAME, 'from': f'{year}-01-01T00:00:00Z', 'to': f'{year}-12-31T23:59:59Z'}
        cal_request = simple_request('get_streaks_calendar', cal_query, variables)
        weeks = cal_request.json()['data']['user']['contributionsCollection']['contributionCalendar']['weeks']
        for week in weeks:
            for day in week['contributionDays']:
                day_counts[day['date']] = day['contributionCount']

    # Longest streak across all recorded days.
    longest = current_run = 0
    for date in sorted(day_counts):
        if day_counts[date] > 0:
            current_run += 1
            longest = max(longest, current_run)
        else:
            current_run = 0

    # Current streak walking backward from today (today counting 0 is allowed -
    # the day may simply not have a commit yet).
    current = 0
    cursor = datetime.date.today()
    if day_counts.get(cursor.isoformat(), 0) == 0:
        cursor -= datetime.timedelta(days=1)
    while day_counts.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= datetime.timedelta(days=1)
    return current, longest


def render_language_rows(root, rows):
    """Rebuild the <g id='lang_rows'> group from live language data."""
    group = root.find(f".//*[@id='lang_rows']")
    if group is None:
        return
    for child in list(group):
        group.remove(child)
    for index, (name, percentage, colour) in enumerate(rows):
        if index >= len(LANG_ROW_Y):
            break
        text = etree.SubElement(group, svg_tag('text'))
        text.set('x', '50')
        text.set('y', str(LANG_ROW_Y[index]))
        text.set('font-size', '12')
        square = etree.SubElement(text, svg_tag('tspan'))
        square.set('fill', colour)
        square.text = '■ '
        label = etree.SubElement(text, svg_tag('tspan'))
        label.set('class', 'leftAccent')
        label.text = f'{name[:11]:<12}'
        bar = etree.SubElement(text, svg_tag('tspan'))
        bar.set('class', 'leftMain')
        bar.text = make_bar(percentage)
        pct = etree.SubElement(text, svg_tag('tspan'))
        pct.set('class', 'leftMuted')
        pct.text = f'  {round(percentage):>2}%'


def render_streak_rows(root, current, longest):
    """Rebuild the <g id='streak_rows'> group from live streak data."""
    group = root.find(f".//*[@id='streak_rows']")
    if group is None:
        return
    for child in list(group):
        group.remove(child)
    values = {'current': current, 'longest': longest}
    for label in ('current', 'longest'):
        text = etree.SubElement(group, svg_tag('text'))
        text.set('x', '30')
        text.set('y', str(STREAK_ROW_Y[label]))
        text.set('font-size', '12')
        name = etree.SubElement(text, svg_tag('tspan'))
        name.set('class', 'leftAccent')
        name.text = f'{label:<9}'
        bar = etree.SubElement(text, svg_tag('tspan'))
        bar.set('class', 'leftMain')
        bar.text = make_streak_bar(values[label], longest)
        days = etree.SubElement(text, svg_tag('tspan'))
        days.set('class', 'leftMuted')
        days.text = f'  {values[label]} days'


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data, lang_rows=None, streak=None):
    """
    Parse SVG files and update elements with my age, commits, stars, repositories, and lines written
    """
    tree = etree.parse(filename)
    root = tree.getroot()
    find_and_replace(root, 'age_data', age_data)
    justify_format(root, 'commit_data', commit_data, 25)
    justify_format(root, 'star_data', star_data, 14)
    justify_format(root, 'repo_data', repo_data, 6)
    justify_format(root, 'contrib_data', contrib_data, 4)
    justify_format(root, 'follower_data', follower_data, 10)
    justify_format(root, 'loc_data', loc_data[2], 9)
    justify_format(root, 'loc_add', loc_data[0])
    justify_format(root, 'loc_del', loc_data[1], 7)
    align_static_fields(root)
    if lang_rows:
        render_language_rows(root, lang_rows)
    if streak is not None:
        render_streak_rows(root, streak[0], streak[1])
    find_and_replace(root, 'panel_updated', 'updated ' + datetime.date.today().strftime('%b %d %Y') + '  ·  via GitHub API')
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    """
    Updates and formats the text of the element, and modifes the amount of dots in the previous element to justify the new text on the svg
    """
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    dot_count = max(0, length - len(new_text))
    dot_string = ' ' + ('.' * dot_count) + ' '
    find_and_replace(root, f"{element_id}_dots", dot_string)


def align_static_fields(root):
    """
    Auto-adjust dot leaders for static profile rows so dots stop at each value start.
    """
    for element_id, prefix_width in STATIC_FIELD_PREFIX_WIDTHS.items():
        element = root.find(f".//*[@id='{element_id}']")
        if element is None:
            continue
        field_width = max(0, STATIC_ROW_TARGET_WIDTH - prefix_width - 2)
        justify_format(root, element_id, element.text or '', field_width)


def find_and_replace(root, element_id, new_text):
    """
    Finds the element in the SVG file and replaces its text with a new value
    """
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = str(new_text)


def commit_counter(comment_size):
    """
    Counts up my total commits, using the cache file created by cache_builder.
    """
    total_commits = 0
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt' # Use the same filename as cache_builder
    with open(filename, 'r') as f:
        data = f.readlines()
    cache_comment = data[:comment_size] # save the comment block
    data = data[comment_size:] # remove those lines
    for line in data:
        total_commits += int(line.split()[2])
    return total_commits


def user_getter(username):
    """
    Returns the account ID and creation time of the user
    """
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']

def follower_getter(username):
    """
    Returns the number of followers of the user
    """
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def query_count(funct_id):
    """
    Counts how many times the GitHub GraphQL API is called
    """
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    """
    Calculates the time it takes for a function to run
    Returns the function result and the time differential
    """
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference, funct_return=False, whitespace=0):
    """
    Prints a formatted time differential
    Returns formatted result if whitespace is specified, otherwise returns raw result
    """
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    print('{:>12}'.format('%.4f' % difference + ' s ')) if difference > 1 else print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


def parse_birthday(acc_date):
    """
    Uses BIRTH_DATE (YYYY-MM-DD) if provided, otherwise falls back to account creation date.
    """
    birth_date = os.environ.get('BIRTH_DATE')
    if birth_date:
        return datetime.datetime.strptime(birth_date, '%Y-%m-%d')
    return datetime.datetime.strptime(acc_date[:10], '%Y-%m-%d')


if __name__ == '__main__':
    """
    Andrew Grant (Andrew6rant), 2022-2025
    """
    print('Calculation times:')
    # define global variable for owner ID and calculate user's creation date
    # e.g {'id': 'MDQ6VXNlcjU3MzMxMTM0'} and 2019-11-03T21:15:07Z for username 'Andrew6rant'
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    formatter('account data', user_time)
    age_data, age_time = perf_counter(daily_readme, parse_birthday(acc_date))
    formatter('age calculation', age_time)
    total_loc, loc_time = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], 7)
    formatter('LOC (cached)', loc_time) if total_loc[-1] else formatter('LOC (no cache)', loc_time)
    commit_data, commit_time = perf_counter(commit_counter, 7)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    contrib_data, contrib_time = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

    # several repositories that I've contributed to have since been deleted.
    if OWNER_ID == {'id': 'MDQ6VXNlcjU3MzMxMTM0'}: # only calculate for user Andrew6rant
        archived_data = add_archive()
        for index in range(len(total_loc)-1):
            total_loc[index] += archived_data[index]
        contrib_data += archived_data[-1]
        commit_data += int(archived_data[-2])

    for index in range(len(total_loc)-1): total_loc[index] = '{:,}'.format(total_loc[index]) # format added, deleted, and total LOC

    # Left-panel modules: top-language breakdown and contribution streaks.
    lang_rows, lang_time = perf_counter(language_breakdown, 6)
    formatter('language breakdown', lang_time)
    streak, streak_time = perf_counter(get_streaks)
    formatter('streak calculation', streak_time)

    svg_overwrite('dark_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1], lang_rows, streak)
    svg_overwrite('light_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1], lang_rows, streak)

    # move cursor to override 'Calculation times:' with 'Total function time:' and the total function time, then move cursor back
    print('\033[F\033[F\033[F\033[F\033[F\033[F\033[F\033[F',
        '{:<21}'.format('Total function time:'), '{:>11}'.format('%.4f' % (user_time + age_time + loc_time + commit_time + star_time + repo_time + contrib_time + follower_time)),
        ' s \033[E\033[E\033[E\033[E\033[E\033[E\033[E\033[E', sep='')

    print('Total GitHub GraphQL API calls:', '{:>3}'.format(sum(QUERY_COUNT.values())))
    for funct_name, count in QUERY_COUNT.items(): print('{:<28}'.format('   ' + funct_name + ':'), '{:>6}'.format(count))
