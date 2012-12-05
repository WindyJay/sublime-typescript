# -*- coding: utf-8 -*-

import sublime, sublime_plugin
from subprocess import Popen, PIPE
import json
from os import path
from threading import Thread, RLock
from time import sleep


# ================ SERVER AND COMMUNICATION HELPERS =============== #

p = Popen(["node", "bin/main.js"], stdin=PIPE, stdout=PIPE)
#prlock = RLock()

def msg(*args):
    res = None
    message = json.dumps(args) + "\n"
    # print "Message : ", message
    p.stdin.write(message)
    res = json.loads(p.stdout.readline())
    return res

def serv_add_file(file_name):
	resp = msg("add_file", file_name)
	# print resp

def serv_update_file(file_name, content):
    resp = msg("update_script", file_name, content)
    # print resp

def serv_get_completions(file_name, pos, is_member):
    resp = msg("complete", file_name, pos, is_member)
    # print resp
    return resp["result"]

def serv_get_errors(file_name):
    resp = msg("get_errors", file_name)
    # print resp
    return resp["result"]

# ========================== GENERAL HELPERS ======================= #

def is_ts(view):
	return view.file_name() and view.file_name().endswith(".ts")

global thread_typescript_update
thread_typescript_update = None
do_thread_update = False

def init_view(view):
    print "is_ts view :", is_ts(view)
    if is_ts(view):
        serv_add_file(view.file_name())

def update_server_code(view):
    if is_ts(view):
        content = view.substr(sublime.Region(0, view.size()-1))
        serv_update_file(view.file_name(), content)

def update_server_code_thread():
    while True:
        view = sublime.active_window().active_view()
        update_server_code(view)
        print "in update_server_code, buffer_id = ", view.buffer_id()
        sleep(1)

def format_completion_entry(c_entry):
    prefix = ""
    if c_entry["kind"] == "method":
        prefix = u"⊳"
    else:
        prefix = u"→"
    prefix += " "

    middle = c_entry["name"]
    if c_entry["kind"] == "method":
        middle += "()"

    suffix = "\t" + c_entry["type"]

    return prefix + middle + suffix

def completions_ts_to_sublime(json_completions):
    return [(format_completion_entry(c), c["name"]) for c in json_completions["entries"]]

def ts_errors_to_regions(ts_errors):
    return [sublime.Region(e["minChar"], e["limChar"]) for e in ts_errors]

global errors_intervals
errors_intervals = {}
def set_errors_intervals(ts_errors):
    global errors_intervals
    errors_intervals = {}
    for e in ts_errors:
        errors_intervals[(e["minChar"], e["limChar"])] = e["message"]

def get_error_for_pos(pos):
    for (l, h), error in errors_intervals.iteritems():
        if pos >= l and pos <= h:
            return error
    return None

def get_pos(view):
    return view.sel()[0].begin()

def handle_errors(view, ts_errors):
    print "IN HANDLE ERRORS, ", ts_errors
    set_errors_intervals(ts_errors)
    print "ERRORS INTERVALS :", errors_intervals
    view.add_regions("typescript_errors", ts_errors_to_regions(ts_errors), "typescript.errors", "cross", sublime.DRAW_EMPTY_AS_OVERWRITE)

def show_current_error(view):
    pos = view.sel()[0].begin()

def set_error_status(view):
    error = get_error_for_pos(get_pos(view))
    if error:
        sublime.status_message(error)
    else:
        sublime.status_message("")


# ========================= INITIALIZATION ======================== #

# Iterate on every open view, add file to server if needed
for window in sublime.windows():
	for view in window.views():
		init_view(view)

# ========================= EVENT HANDLERS ======================== #

class TypescriptComplete(sublime_plugin.TextCommand):

    def run(self, edit, characters):
        # Insert the autocomplete char
        for region in self.view.sel():
            self.view.insert(edit, region.end(), characters)
        # Update the code on the server side for the current file
        update_server_code(self.view)
        self.view.run_command("auto_complete")

def handle_async_worker(view):
    def worker():
        # Update the script
        update_server_code(view)
        # Get errors
        errors = serv_get_errors(view.file_name())
        handle_errors(view, errors)
        set_error_status(view)
        sleep(1)
        worked_views[view.buffer_id()] = False
    return worker

worked_views = {}
class TestEvent(sublime_plugin.EventListener):

    def on_load(self, view):
        print "IN ON LOAD"
        init_view(view)

    def on_modified(self, view):
        if view.is_loading(): return
        if is_ts(view):
            print "in on_modified, ", worked_views
            if not worked_views.get(view.buffer_id(), False):
                worked_views[view.buffer_id()] = True
                Thread(target=handle_async_worker(view)).start()
            set_error_status(view)

    def on_selection_modified(self, view):
        if is_ts(view):
            set_error_status(view)

    def on_query_completions(self, view, prefix, locations):
        if is_ts(view):
            # Get the position of the cursor (first one in case of multiple sels)
            pos = view.sel()[0].begin()
            line = view.substr(sublime.Region(view.word(pos-1).a, pos))
            # Determine wether it is a member completion or not
            is_member = line.endswith(".")
            completions_json = serv_get_completions(view.file_name(), pos, is_member)
            set_error_status(view)
            return completions_ts_to_sublime(completions_json)


    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "typescript":
            view = sublime.active_window().active_view()
            return is_ts(view)

# msg("add_file", "bin/test_code.ts")
