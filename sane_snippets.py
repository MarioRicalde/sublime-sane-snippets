#coding: utf8
#################################### IMPORTS ###################################

# Std Libs
import os
import re
import textwrap
import bisect
import plistlib
import glob
import uuid

# Sublime Libs
import sublime
import sublime_plugin

#################################### REGEXES ###################################

# Just using
template      = re.compile('^---\n(.*?)\n---\n(.*)$', re.DOTALL | re.MULTILINE)

line_template = re.compile('^(.*?):\s*(.*)$')

################################### CONSTANTS ##################################

# NT invalid path characters
INVALID_PATH_CHARS = map(chr,range(33) + [16,34,38,42,44,47,58,60,62,63,92,124])
INVALID_PATH_RE    = re.compile('|'.join(map(re.escape, INVALID_PATH_CHARS)))

#################################### HELPERS ###################################

def get_tab_size(view):
    return int(view.settings().get('tab_size', 8))

def normed_indentation_pt(view, sel, non_space=False):
    tab_size = get_tab_size(view)
    pos      = 0
    ln       = view.line(sel)

    for pt in xrange(ln.begin(), ln.end() if non_space else sel.begin()):
        ch = view.substr(pt)

        if ch == '\t':
            pos += tab_size - (pos % tab_size)

        elif ch.isspace():
            pos += 1

        elif non_space:
            break
        else:
            pos+=1

    return pos

def shares_extents(r1, r2):
    return set([r1.a, r1.b]).intersection(set([r2.a, r2.b]) )

def inversion_stream(view, regions, start=None, end=None):
    n = (len(regions) * 2) - 1

    end   = end   or view.size()
    start = start or 0

    def inner():
        for reg in regions:
            yield reg.begin()
            yield reg.end()

    for i, pt in enumerate(inner()):
        if i == 0:
            if pt == start: continue
            else:       yield start

        elif i == n:
            if pt != end:
                yield pt
                yield end

            continue

        yield pt

def invert_regions(view=None, regions=[], spanning=False):
    inverted = []

    if spanning is not False: # regions empty eval as False
        span_start = spanning.begin()
        span_end   = spanning.end()
    else:
        span_start = None
        span_end = None

    for i, pt in enumerate(inversion_stream(view, regions, span_start, span_end)):
        if i%2 == 0: start = pt
        else: inverted.append(sublime.Region(start, pt))

    return inverted or [sublime.Region(0, 0)]


def extract_snippet(view, edit):
    # Reset start end_points
    span               = view.sel()[0].cover(view.sel()[-1])
    tab_stops          = [s for s in view.sel() if not
                          (shares_extents(s, span) and s.empty())]
    snippet            = [ normed_indentation_pt(view, span, non_space=True) *
                           ' ']
    tab_stop_map       = {}
    i                  = 0

    for region in [ sublime.Region(r.begin(), r.end(), 666) for r in
                    invert_regions(regions=tab_stops, spanning=span) ]:
        bisect.insort(tab_stops, region)

    for region in tab_stops:
        text = (view.substr(region)
                    .replace('\\', '\\\\')
                    .replace('$', '\\$'))
        i+=1

        if region.xpos() != 666:
            tab_stop_index = tab_stop_map.get(text, i)
            if tab_stop_index == i and text: tab_stop_map[text] = i
            text = '${%s:%s}' % (tab_stop_index + 100, text.replace('}', '\\}'))

        snippet.append(text)

    return textwrap.dedent(''.join(snippet)).lstrip()

################################################################################

def parse_snippet(name, text):
    snippet = {
        'description': name,
        'tabTrigger':  None,
        'scope':       None,
        'uuid': None,
    }

    (frontmatter, content) = template.search(text).groups()
    snippet['content'] = content

    for line in frontmatter.split('\n'):
        (key, val) = [v.strip() for v in line_template.match(line).groups()]
        snippet[key] = val

    if not 'name' in snippet:
        snippet['name'] = snippet['description']

    return snippet

def folder_and_path_to_write(path, snippet):
    folder  = os.path.dirname(path)
    folder  = os.path.join(folder, '.compiled')

    ext     = '.sane.tmSnippet'
    fpath   =  os.path.join( folder, 
                            
                            ''.join((
                            slug(snippet['description']),
                            '-', 
                            snippet['uuid'], ))
                            )
    
    return folder, fpath, ext

def write_snippet(path, snippet):
    if  snippet['uuid'] == None:
        return sublime.error_message("Snippet for %s is missing uuid" % path)

    folder, fpath, ext = folder_and_path_to_write(path, snippet)
    
    try:os.makedirs(folder)
    except:pass

    snippet = dict((k,v) for (k,v) in snippet.items() if v is not None)

    with open(fpath + ext, 'w') as fh:
        plistlib.writePlist(snippet, fh)

def valid_nt_path(path):
    "Removes all illegal characters from pathname and replaces with `-`"

    return re.sub('-+', '-', INVALID_PATH_RE.sub('-', path)).strip('- ')

def slug(s):
    s = s.decode('utf-8')
    s = re.sub(' +', ' ', s.encode('ascii', 'ignore'))
    return valid_nt_path(s)

def regenerate_snippets():
    snippets = {}

    # Check Packages folder
    for root, dirs, files in os.walk(sublime.packages_path()):

        # Unlink old snippets
        for name in files:
            try:
                if name.endswith('.sane.tmSnippet'):
                    os.unlink(os.path.join(root, name))
            except:
                pass

        # Create new snippets
            try:
                if name.endswith('.sane-snippet'):
                    path = os.path.join(root, name)

                    with open(path, 'rU') as f:
                        snippets['path'] = parse_snippet (
                            os.path.splitext(name)[0], f.read() )
            except:
                pass

    # Dump new snippets
    for path, snippet in snippets.items():
        write_snippet(path, snippet)

# And watch for updated snippets
class SaneSnippet(sublime_plugin.EventListener):
    def on_post_save(self, view):
        if (view.file_name().endswith('.sane-snippet')):
            path = view.file_name()

            with open(path, 'rU') as f:
                snippet = parse_snippet (
                    os.path.splitext(os.path.basename(path))[0], f.read() )

            try:
                folder, fpath, ext = folder_and_path_to_write(path, snippet)
                os.path.join(folder,   snippet['uuid'])

                fpath   = os.path.join( folder, 
                                        
                                        ''.join((
                                        '*',
                                        '-', 
                                        snippet['uuid'])
                                        
                                        ))
                
                have_old = glob.glob(fpath)
                if have_old:
                    os.unlink(have_old[0])
                print "Deleted old sane.tmSnippet"
            except Exception, e:
                print e

            write_snippet(view.file_name(), snippet)

class RegenerateSaneSnippets(sublime_plugin.TextCommand):
    def run(self, **kw):
        regenerate_snippets()

def get_scope(view):
    pt = view.sel() and view.sel()[0].begin() or 0
    return " ".join (
         t.strip() for t in reversed(view.syntax_name(pt).split()) )

def scope_as_snippet(view):
    scope = get_scope(view).split()
    return '${4:%s} ${5:%s}' % (scope[0], ' '.join(scope[1:]))

class ExtractSaneSnippet(sublime_plugin.TextCommand):
    def is_enabled(self, args=[]):
        view = self.view
        sels = list(view.sel())
        return len(sels)

    def run(self, edit, snippets=[]):
        view   = self.view

        contents     = extract_snippet(view, edit)
        scope        = scope_as_snippet(view)
        the_uuid     = str(uuid.uuid1()) # .hex isn't ffff-ffff- format

        snippet ="""\
---
name: ${1:name}
tabTrigger: ${2:tabTrigger}
scope: ${3:%(scope)s}
uuid: ${6:%(uuid)s}
---
%(contents)s"""

        snippet = snippet % dict(scope=scope, uuid=the_uuid, contents=contents)
        view.run_command('new_sane_snippet', dict(snippet=snippet))
        
        print snippet
        
        
        
