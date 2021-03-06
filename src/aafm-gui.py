#!/usr/bin/env python2

try:
    import pygtk
except ImportError:
    print 'The Python module pyGTK is not installed.  Please install it.  See the README for instructions.'

    try:
        import Tkinter

        Tkinter.Tk().withdraw()
        import tkMessageBox

        tkMessageBox.showinfo("Unable to start aafm",
                              "The Python module pyGTK is not installed.  Please see the README file for instructions on how to download and install pyGTK.")
    except:
        pass

pygtk.require('2.0')
import gtk
import gobject
import glib
import os
import string
import shutil
import socket
import datetime
import stat
import pwd
import grp
import urllib
import ConfigParser

if os.name == 'nt':
    import win32security

from TreeViewFile import TreeViewFile
from Aafm import Aafm


class Aafm_GUI:
    QUEUE_ACTION_COPY_TO_DEVICE = 'copy_to_device'
    QUEUE_ACTION_COPY_FROM_DEVICE = 'copy_from_device'
    QUEUE_ACTION_MOVE_IN_DEVICE = 'move_in_device'
    QUEUE_ACTION_MOVE_IN_HOST = 'move_in_host'

    # These constants are for dragging files to Nautilus
    XDS_ATOM = gtk.gdk.atom_intern("XdndDirectSave0")
    TEXT_ATOM = gtk.gdk.atom_intern("text/plain")
    XDS_FILENAME = 'whatever.txt'

    def __init__(self):

        self.done = True
        self.devices_list = []
        self.showing_notice = False
        self.progress_value = None

        # Read settings
        self.config = ConfigParser.SafeConfigParser({'lastdir_host': '', 'lastdir_device': '',
                                                     'startdir_host': 'last', 'startdir_host_path': '',
                                                     'startdir_device': 'last', 'startdir_device_path': '',
                                                     'show_hidden': 'no', 'show_modified': 'yes',
                                                     'show_permissions': 'no', 'show_owner': 'no',
                                                     'show_group': 'no', 'last_serial': '',
                                                     'last_ip': ''})
        self.config_file_loc = ""
        self.config_file_loc_default = os.path.join(os.path.expanduser("~"), ".aafm")
        for file_loc in os.curdir, os.path.expanduser("~"), os.environ.get("AAFM_CONF"):
            try:
                if file_loc is not None:
                    with open(os.path.join(file_loc, ".aafm")) as source:
                        self.config.readfp(source)
                        self.config_file_loc = file_loc
                        break
            except IOError:
                pass

        # Test for the aafm section and add it if it's missing
        try:
            self.config.get("aafm", "startdir_host")
        except ConfigParser.NoSectionError:
            self.config.add_section("aafm")

        # Store config variables
        self.startDirHost = self.config.get("aafm", "startdir_host")
        self.startDirHostPath = self.config.get("aafm", "startdir_host_path")
        self.startDirDevice = self.config.get("aafm", "startdir_device")
        self.startDirDevicePath = self.config.get("aafm", "startdir_device_path")
        self.showHidden = (self.config.get("aafm", "show_hidden") == "yes")
        self.showModified = (self.config.get("aafm", "show_modified") == "yes")
        self.showPermissions = (self.config.get("aafm", "show_permissions") == "yes")
        self.showOwner = (self.config.get("aafm", "show_owner") == "yes")
        self.showGroup = (self.config.get("aafm", "show_group") == "yes")
        self.lastDeviceSerial = self.config.get("aafm", "last_serial")
        self.lastDeviceIP = self.config.get("aafm", "last_ip")

        if self.startDirHost == 'last':
            self.host_cwd = self.config.get("aafm", "lastdir_host")
        else:
            self.host_cwd = self.startDirHostPath

        if not os.path.isdir(self.host_cwd):
            self.host_cwd = os.path.expanduser("~")

        if self.startDirDevice == 'last':
            self.device_cwd_default = self.config.get("aafm", "lastdir_device")
        else:
            self.device_cwd_default = self.startDirDevicePath

        if self.device_cwd_default == '':
            self.device_cwd_default = '/mnt/sdcard'

        self.device_cwd = self.device_cwd_default

        # The super core
        self.aafm = Aafm('adb', self.host_cwd, self.device_cwd, self)
        self.queue = []

        self.basedir = os.path.dirname(os.path.abspath(__file__))

        if os.name == 'nt':
            self.get_owner = self._get_owner_windows
            self.get_group = self._get_group_windows
        else:
            self.get_owner = self._get_owner
            self.get_group = self._get_group

        # Build main window from XML
        builder = gtk.Builder()
        builder.add_from_file(os.path.join(self.basedir, "data/glade/interface.xml"))
        builder.connect_signals({"on_window_destroy": self.destroy})
        self.window = builder.get_object("window")
        vbox1 = builder.get_object("vbox1")

        # Set preferences window var
        self.window_prefs = None

        # Build menu from XML
        uimanager = gtk.UIManager()
        accelgroup = uimanager.get_accel_group()
        self.window.add_accel_group(accelgroup)

        actiongroup = gtk.ActionGroup('Main')
        actiongroup.add_actions([('Preferences', gtk.STOCK_PREFERENCES, '_Preferences', None,
                                  'Preferences', self.open_prefs),
                                 ('Quit', gtk.STOCK_QUIT, '_Quit', None,
                                  'Quit aafm', self.destroy),
                                 ('File', None, '_File')])
        uimanager.insert_action_group(actiongroup, 0)

        uimanager.add_ui_from_file(os.path.join(self.basedir, "data/glade/menu.xml"))
        menubar = uimanager.get_widget('/MenuBar')

        vbox1.pack_start(menubar, False, False, 0)
        vbox1.reorder_child(menubar, 0)

        imageDir = gtk.Image()
        imageDir.set_from_file(os.path.join(self.basedir, "data/icons/folder.png"))
        imageFile = gtk.Image()
        imageFile.set_from_file(os.path.join(self.basedir, "data/icons/file.png"))

        # Show hidden files and folders
        showHidden = builder.get_object('showHidden')
        showHidden.set_active(self.showHidden)
        showHidden.connect('toggled', self.on_toggle_hidden)

        # Progress bar
        self.progress_bar = builder.get_object('progressBar')

        # Host and device TreeViews

        # HOST
        self.host_treeViewFile = TreeViewFile(imageDir.get_pixbuf(), imageFile.get_pixbuf(), self.showModified,
                                              self.showPermissions, self.showOwner, self.showGroup)

        hostFrame = builder.get_object('frameHost')
        hostFrame.get_child().add(self.host_treeViewFile.get_view())

        hostTree = self.host_treeViewFile.get_tree()
        hostTree.connect('row-activated', self.host_navigate_callback)
        hostTree.connect('button_press_event', self.on_host_tree_view_contextual_menu)

        host_targets = [
            ('DRAG_SELF', gtk.TARGET_SAME_WIDGET, 0),
            ('ADB_text', 0, 1),
            ('text/plain', 0, 2)
        ]

        hostTree.enable_model_drag_dest(
            host_targets,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE
        )
        hostTree.connect('drag-data-received', self.on_host_drag_data_received)

        hostTree.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            host_targets,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE
        )
        hostTree.connect('drag_data_get', self.on_host_drag_data_get)

        self.hostFrame = hostFrame
        self.hostName = socket.gethostname()


        # DEVICE
        self.device_treeViewFile = TreeViewFile(imageDir.get_pixbuf(), imageFile.get_pixbuf(), self.showModified,
                                                self.showPermissions, self.showOwner, self.showGroup)

        deviceFrame = builder.get_object('frameDevice')
        deviceFrame.get_child().add(self.device_treeViewFile.get_view())

        deviceTree = self.device_treeViewFile.get_tree()
        deviceTree.connect('row-activated', self.device_navigate_callback)
        deviceTree.connect('button_press_event', self.on_device_tree_view_contextual_menu)

        device_targets = [
            ('DRAG_SELF', gtk.TARGET_SAME_WIDGET, 0),
            ('ADB_text', 0, 1),
            ('XdndDirectSave0', 0, 2),
            ('text/plain', 0, 3)
        ]

        deviceTree.enable_model_drag_dest(
            device_targets,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE
        )
        deviceTree.connect('drag-data-received', self.on_device_drag_data_received)

        deviceTree.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            device_targets,
            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE
        )
        deviceTree.connect('drag-data-get', self.on_device_drag_data_get)
        deviceTree.connect('drag-begin', self.on_device_drag_begin)

        self.deviceFrame = deviceFrame

        # Add device button
        addDevice = builder.get_object('addDevice')
        addDevice.connect('clicked', self.on_clicked_add_device)

        # Devices list combobox
        self.devicesList = builder.get_object('devicesList')
        self.devices_list_store = gtk.ListStore(gobject.TYPE_STRING)
        self.refresh_devices_list(True, self.lastDeviceSerial)
        self.devicesList.set_model(self.devices_list_store)

        cell = gtk.CellRendererText()
        self.devicesList.pack_start(cell, True)
        self.devicesList.add_attribute(cell, "text", 0)

        # if self.lastDeviceSerial in self.devices_list:
        #    self.aafm.set_device(self.lastDeviceSerial)
        #elif len(self.devices_list) > 0:
        #    self.aafm.set_device(self.aafm.get_device_serial(self.devices_list[0]))

        self.devicesList.connect('changed', self.on_change_device)

        # Devices list refresh button
        refreshDevicesList = builder.get_object('refreshDevicesList')
        refreshDevicesList.connect('clicked', self.on_clicked_refresh_devices)

        # Some more subtle details...
        try:
            self.window.set_icon_from_file(os.path.join(self.basedir, "data/icons/aafm.svg"))
        except:
            self.window.set_icon_from_file(os.path.join(self.basedir, "data/icons/aafm.png"))
            # self.adb = 'adb'

        self.refresh_host_files()

        # And we're done!
        self.window.show_all()


    def host_navigate_callback(self, widget, path, view_column):

        row = path[0]
        model = widget.get_model()
        iter = model.get_iter(row)
        is_dir = model.get_value(iter, 0)
        name = model.get_value(iter, 1)

        if is_dir:
            self.host_cwd = os.path.normpath(os.path.join(self.host_cwd, name))
            self.aafm.set_host_cwd(self.host_cwd)
            self.refresh_host_files()


    def device_navigate_callback(self, widget, path, view_column):

        row = path[0]
        model = widget.get_model()
        iter = model.get_iter(row)
        is_dir = model.get_value(iter, 0)
        name = model.get_value(iter, 1)

        if is_dir:
            self.device_cwd = self.aafm.device_path_normpath(self.aafm.device_path_join(self.device_cwd, name))
            self.aafm.set_device_cwd(self.device_cwd)
            self.refresh_device_files()


    def refresh_host_files(self):
        self.host_treeViewFile.load_data(self.dir_scan_host(self.host_cwd))
        self.hostFrame.set_label(self.host_cwd)


    def refresh_device_files(self):
        print 'Refreshing device files'
        if self.aafm.device != '':
            self.device_treeViewFile.load_data(self.dir_scan_device(self.device_cwd))
            self.deviceFrame.set_label(self.device_cwd)
        else:
            self.device_treeViewFile.clear_data()

    def get_treeviewfile_selected(self, treeviewfile):
        values = []
        model, rows = treeviewfile.get_tree().get_selection().get_selected_rows()

        for row in rows:
            iter = model.get_iter(row)
            filename = model.get_value(iter, 1)
            is_directory = model.get_value(iter, 0)
            values.append({'filename': filename, 'is_directory': is_directory})

        return values


    def get_host_selected_files(self):
        return self.get_treeviewfile_selected(self.host_treeViewFile)

    def get_device_selected_files(self):
        return self.get_treeviewfile_selected(self.device_treeViewFile)

    def human_readable_size(self, size):
        for x in ['B', 'K', 'M', 'G']:
            if size < 1024.0:
                return "%3.1f%s" % (size, x)
            size /= 1024.0
        return "%3.1f%s" % (size, 'T')

    """ Walks through a directory and return the data in a tree-style list
        that can be used by the TreeViewFile """

    def dir_scan_host(self, directory):
        output = []

        root, dirs, files = next(os.walk(directory))

        if not self.showHidden:
            files = [f for f in files if not f[0] == '.']
            dirs = [d for d in dirs if not d[0] == '.']

        dirs.sort()
        files.sort()

        output.append({'directory': True, 'name': '..', 'size': 0, 'timestamp': '',
                       'permissions': '',
                       'owner': '',
                       'group': ''})

        for d in dirs:
            path = os.path.join(directory, d)
            output.append({
                'directory': True,
                'name': d,
                'size': 0,
                'timestamp': self.format_timestamp(os.path.getmtime(path)),
                'permissions': self.get_permissions(path),
                'owner': self.get_owner(path),
                'group': self.get_group(path)
            })

        for f in files:
            path = os.path.join(directory, f)

            try:
                size = self.human_readable_size(os.path.getsize(path))
                output.append({
                    'directory': False,
                    'name': f,
                    'size': size,
                    'timestamp': self.format_timestamp(os.path.getmtime(path)),
                    'permissions': self.get_permissions(path),
                    'owner': self.get_owner(path),
                    'group': self.get_group(path)
                })
            except OSError:
                pass

        return output

    """ The following three methods are probably NOT the best way of doing things.
    At least according to all the warnings that say os.stat is very costly
    and should be cached."""

    def get_permissions(self, filename):
        st = os.stat(filename)
        mode = st.st_mode
        permissions = ''

        bits = [
            stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR,
            stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP,
            stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH
        ]

        attrs = ['r', 'w', 'x']

        for i in range(0, len(bits)):
            bit = bits[i]
            attr = attrs[i % len(attrs)]

            if bit & mode:
                permissions += attr
            else:
                permissions += '-'

        return permissions

    def _get_owner(self, filename):
        st = os.stat(filename)
        uid = st.st_uid
        try:
            user = pwd.getpwuid(uid)[0]
        except KeyError:
            print 'unknown uid %d for file %s' % (uid, filename)
            user = 'unknown'
        return user

    def _get_owner_windows(self, filename):
        sd = win32security.GetFileSecurity(filename, win32security.OWNER_SECURITY_INFORMATION)
        owner_sid = sd.GetSecurityDescriptorOwner()
        name, domain, type = win32security.LookupAccountSid(None, owner_sid)
        return name

    def _get_group(self, filename):
        st = os.stat(filename)
        gid = st.st_gid
        try:
            groupname = grp.getgrgid(gid)[0]
        except KeyError:
            print 'unknown gid %d for file %s' % (gid, filename)
            groupname = 'unknown'
        return groupname

    def _get_group_windows(self, filename):
        return ""


    def format_timestamp(self, timestamp):
        d = datetime.datetime.fromtimestamp(timestamp)
        return d.strftime(r'%Y-%m-%d %H:%M')

    """ Like dir_scan_host, but in the connected Android device """

    def dir_scan_device(self, directory):
        output = []

        entries = self.aafm.get_device_file_list()

        dirs = []
        files = []

        for filename, entry in entries.iteritems():
            if entry['is_directory']:
                dirs.append(filename)
            else:
                files.append(filename)

        if not self.showHidden:
            files = [f for f in files if not f[0] == '.']
            dirs = [d for d in dirs if not d[0] == '.']

        dirs.sort()
        files.sort()

        output.append(
            {'directory': True, 'name': '..', 'size': 0, 'timestamp': '', 'permissions': '', 'owner': '', 'group': ''})

        for d in dirs:
            output.append({
                'directory': True,
                'name': d,
                'size': 0,
                'timestamp': self.format_timestamp(entries[d]['timestamp']),
                'permissions': entries[d]['permissions'],
                'owner': entries[d]['owner'],
                'group': entries[d]['group']
            })

        for f in files:
            size = self.human_readable_size(int(entries[f]['size']))
            output.append({
                'directory': False,
                'name': f,
                'size': size,
                'timestamp': self.format_timestamp(entries[f]['timestamp']),
                'permissions': entries[f]['permissions'],
                'owner': entries[f]['owner'],
                'group': entries[f]['group']
            })

        return output

    def on_host_tree_view_contextual_menu(self, widget, event):
        if event.button == 3:  # Right click
            builder = gtk.Builder()
            builder.add_from_file(os.path.join(self.basedir, 'data/glade/menu_contextual_host.xml'))
            menu = builder.get_object('menu')
            builder.connect_signals({
                'on_menuHostCopyToDevice_activate': self.on_host_copy_to_device_callback,
                'on_menuHostCreateDirectory_activate': self.on_host_create_directory_callback,
                'on_menuHostRefresh_activate': self.on_host_refresh_callback,
                'on_menuHostDeleteItem_activate': self.on_host_delete_item_callback,
                'on_menuHostRenameItem_activate': self.on_host_rename_item_callback
            })

            # Ensure only right options are available
            num_selected = len(self.get_host_selected_files())
            has_selection = num_selected > 0

            menuCopy = builder.get_object('menuHostCopyToDevice')
            menuCopy.set_sensitive(has_selection)

            menuDelete = builder.get_object('menuHostDeleteItem')
            menuDelete.set_sensitive(has_selection)

            menuRename = builder.get_object('menuHostRenameItem')
            menuRename.set_sensitive(num_selected == 1)

            menu.popup(None, None, None, event.button, event.time)
            return True

        # Not consuming the event
        return False

    # Copy to device
    def on_host_copy_to_device_callback(self, widget):
        for row in self.get_host_selected_files():
            src = os.path.join(self.host_cwd, row['filename'])
            self.add_to_queue(self.QUEUE_ACTION_COPY_TO_DEVICE, src, self.device_cwd)
        self.process_queue()


    # Create host directory
    def on_host_create_directory_callback(self, widget):
        directory_name = self.dialog_get_directory_name()

        if directory_name is None:
            return

        full_path = os.path.join(self.host_cwd, directory_name)
        if not os.path.exists(full_path):
            os.mkdir(full_path)
            self.refresh_host_files()


    def on_host_refresh_callback(self, widget):
        self.refresh_host_files()


    def on_host_delete_item_callback(self, widget):
        selected = self.get_host_selected_files()
        items = []
        for item in selected:
            items.append(item['filename'])

        result = self.dialog_delete_confirmation(items)

        if result == gtk.RESPONSE_OK:
            for item in items:
                full_item_path = os.path.join(self.host_cwd, item)
                self.delete_item(full_item_path)
                self.refresh_host_files()

    def delete_item(self, path):
        if os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)

    def on_host_rename_item_callback(self, widget):
        old_name = self.get_host_selected_files()[0]['filename']
        new_name = self.dialog_get_item_name(old_name)

        if new_name is None:
            return

        full_src_path = os.path.join(self.host_cwd, old_name)
        full_dst_path = os.path.join(self.host_cwd, new_name)

        shutil.move(full_src_path, full_dst_path)
        self.refresh_host_files()

    def on_device_tree_view_contextual_menu(self, widget, event):
        if event.button == 3:  # Right click
            builder = gtk.Builder()
            builder.add_from_file(os.path.join(self.basedir, "data/glade/menu_contextual_device.xml"))
            menu = builder.get_object("menu")
            builder.connect_signals({
                'on_menuDeviceDeleteItem_activate': self.on_device_delete_item_callback,
                'on_menuDeviceCreateDirectory_activate': self.on_device_create_directory_callback,
                'on_menuDeviceRefresh_activate': self.on_device_refresh_callback,
                'on_menuDeviceCopyToComputer_activate': self.on_device_copy_to_computer_callback,
                'on_menuDeviceRenameItem_activate': self.on_device_rename_item_callback
            })

            # Ensure only right options are available
            num_selected = len(self.get_device_selected_files())
            has_selection = num_selected > 0
            menuDelete = builder.get_object('menuDeviceDeleteItem')
            menuDelete.set_sensitive(has_selection)

            menuCopy = builder.get_object('menuDeviceCopyToComputer')
            menuCopy.set_sensitive(has_selection)

            menuRename = builder.get_object('menuDeviceRenameItem')
            menuRename.set_sensitive(num_selected == 1)

            menu.popup(None, None, None, event.button, event.time)
            return True

        # don't consume the event, so we can still double click to navigate
        return False

    def on_device_delete_item_callback(self, widget):
        selected = self.get_device_selected_files()

        items = []

        for item in selected:
            items.append(item['filename'])

        result = self.dialog_delete_confirmation(items)

        if result == gtk.RESPONSE_OK:
            for item in items:
                full_item_path = self.aafm.device_path_join(self.device_cwd, item)
                self.aafm.device_delete_item(full_item_path)
                self.refresh_device_files()


    def dialog_delete_confirmation(self, items):
        items.sort()
        joined = ', '.join(items)
        dialog = gtk.MessageDialog(
            parent=None,
            flags=gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
            type=gtk.MESSAGE_QUESTION,
            buttons=gtk.BUTTONS_OK_CANCEL,
            message_format="Are you sure you want to delete %d items?" % len(items)
        )
        dialog.format_secondary_markup('%s will be deleted. This action cannot be undone.' % joined)
        dialog.show_all()
        result = dialog.run()

        dialog.destroy()
        return result

    def on_device_create_directory_callback(self, widget):
        directory_name = self.dialog_get_directory_name()

        # dialog was cancelled
        if directory_name is None:
            return

        full_path = self.aafm.device_path_join(self.device_cwd, directory_name)
        self.aafm.device_make_directory(full_path)
        self.refresh_device_files()


    def dialog_get_directory_name(self):
        dialog = gtk.MessageDialog(
            None,
            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
            gtk.MESSAGE_QUESTION,
            gtk.BUTTONS_OK_CANCEL,
            None)

        dialog.set_markup('Please enter new directory name:')

        entry = gtk.Entry()
        entry.connect('activate', self.dialog_response, dialog, gtk.RESPONSE_OK)

        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label('Name:'), False, 5, 5)
        hbox.pack_end(entry)

        dialog.vbox.pack_end(hbox, True, True, 0)
        dialog.show_all()

        result = dialog.run()

        text = entry.get_text()
        dialog.destroy()

        if result == gtk.RESPONSE_OK:
            return text
        else:
            return None


    def dialog_response(self, entry, dialog, response):
        dialog.response(response)


    def on_device_refresh_callback(self, widget):
        self.refresh_device_files()


    def on_device_copy_to_computer_callback(self, widget):
        selected = self.get_device_selected_files()
        task = self.copy_from_device_task(selected)
        gobject.idle_add(task.next)


    def copy_from_device_task(self, rows):
        completed = 0
        total = len(rows)

        self.update_progress()

        for row in rows:
            filename = row['filename']
            is_directory = row['is_directory']

            full_device_path = self.aafm.device_path_join(self.device_cwd, filename)
            full_host_path = self.host_cwd

            self.aafm.copy_to_host(full_device_path, full_host_path)
            completed = completed + 1
            self.refresh_host_files()
            self.update_progress(completed * 1.0 / total)

            yield True

        yield False

    def on_device_rename_item_callback(self, widget):
        old_name = self.get_device_selected_files()[0]['filename']
        new_name = self.dialog_get_item_name(old_name)

        if new_name is None:
            return

        full_src_path = self.aafm.device_path_join(self.device_cwd, old_name)
        full_dst_path = self.aafm.device_path_join(self.device_cwd, new_name)

        self.aafm.device_rename_item(full_src_path, full_dst_path)
        self.refresh_device_files()

    def dialog_get_item_name(self, old_name):
        dialog = gtk.MessageDialog(
            None,
            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
            gtk.MESSAGE_QUESTION,
            gtk.BUTTONS_OK_CANCEL,
            None)

        dialog.set_markup('Please enter new name:')

        entry = gtk.Entry()
        entry.connect('activate', self.dialog_response, dialog, gtk.RESPONSE_OK)
        entry.set_text(old_name)

        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label('Name:'), False, 5, 5)
        hbox.pack_end(entry)

        dialog.vbox.pack_end(hbox, True, True, 0)
        dialog.show_all()

        result = dialog.run()
        text = entry.get_text()
        dialog.destroy()

        if result == gtk.RESPONSE_OK:
            return text
        else:
            return None

    def show_notice(self, notice, flash=False):
        self.showing_notice = True

        if flash:
            self.progress_bar.set_text('!' * 7)
            glib.timeout_add(1000, lambda: self.show_notice(notice))
        else:
            self.progress_bar.set_text(notice)

    def clear_notice(self):
        self.showing_notice = False
        self.update_progress(self.progress_value)

    def update_progress(self, value=None):
        if value is None:
            self.progress_bar.set_fraction(0)
            if not self.showing_notice:
                self.progress_bar.set_text("Ready")
        else:
            self.progress_bar.set_fraction(value)
            if not self.showing_notice:
                self.progress_bar.set_text("%d%%" % (value * 100))

        if value >= 1:
            if not self.showing_notice:
                self.progress_bar.set_text("Done")
            self.progress_bar.set_fraction(0)
            self.done = True

            if len(self.devices_list) > 0:
                self.devicesList.set_sensitive(True)
        else:
            self.done = False

        self.progress_value = value

    def on_host_drag_data_get(self, widget, context, selection, target_type, time):
        data = '\n'.join(['file://' + urllib.quote(os.path.join(self.host_cwd, item['filename'])) for item in
                          self.get_host_selected_files()])

        selection.set(selection.target, 8, data)


    def on_host_drag_data_received(self, tree_view, context, x, y, selection, info, timestamp):
        data = selection.data
        type = selection.type
        drop_info = tree_view.get_dest_row_at_pos(x, y)
        destination = self.host_cwd

        if drop_info:
            model = tree_view.get_model()
            path, position = drop_info

            if position in [gtk.TREE_VIEW_DROP_INTO_OR_BEFORE, gtk.TREE_VIEW_DROP_INTO_OR_AFTER]:
                iter = model.get_iter(path)
                is_directory = model.get_value(iter, 0)
                name = model.get_value(iter, 1)

                # If dropping over a folder, copy things to that folder
                if is_directory:
                    destination = os.path.join(self.host_cwd, name)

        for line in [line.strip() for line in data.split('\n')]:
            if line.startswith('file://'):
                source = urllib.unquote(line.replace('file://', '', 1))

                if type == 'DRAG_SELF':
                    self.add_to_queue(self.QUEUE_ACTION_MOVE_IN_HOST, source, destination)
                elif type == 'ADB_text':
                    self.add_to_queue(self.QUEUE_ACTION_COPY_FROM_DEVICE, source, destination)

        self.process_queue()


    def on_device_drag_begin(self, widget, context):

        context.source_window.property_change(self.XDS_ATOM, self.TEXT_ATOM, 8, gtk.gdk.PROP_MODE_REPLACE,
                                              self.XDS_FILENAME)


    def on_device_drag_data_get(self, widget, context, selection, target_type, time):

        if selection.target == 'XdndDirectSave0':
            type, format, destination_file = context.source_window.property_get(self.XDS_ATOM, self.TEXT_ATOM)

            if destination_file.startswith('file://'):
                destination = os.path.dirname(urllib.unquote(destination_file).replace('file://', '', 1))
                for item in self.get_device_selected_files():
                    self.add_to_queue(self.QUEUE_ACTION_COPY_FROM_DEVICE,
                                      self.aafm.device_path_join(self.device_cwd, item['filename']), destination)

                self.process_queue()
            else:
                print "ERROR: Destination doesn't start with file://?!!?"


        else:
            selection.set(selection.target, 8, '\n'.join(
                ['file://' + urllib.quote(self.aafm.device_path_join(self.device_cwd, item['filename'])) for item in
                 self.get_device_selected_files()]))


    def on_device_drag_data_received(self, tree_view, context, x, y, selection, info, timestamp):

        data = selection.data
        type = selection.type
        drop_info = tree_view.get_dest_row_at_pos(x, y)
        destination = self.device_cwd

        # When dropped over a row
        if drop_info:
            model = tree_view.get_model()
            path, position = drop_info

            if position in [gtk.TREE_VIEW_DROP_INTO_OR_BEFORE, gtk.TREE_VIEW_DROP_INTO_OR_AFTER]:
                iter = model.get_iter(path)
                is_directory = model.get_value(iter, 0)
                name = model.get_value(iter, 1)

                # If dropping over a folder, copy things to that folder
                if is_directory:
                    destination = self.aafm.device_path_join(self.device_cwd, name)

        if type == 'DRAG_SELF':
            if self.device_cwd != destination:
                for line in [line.strip() for line in data.split('\n')]:
                    if line.startswith('file://'):
                        source = urllib.unquote(line.replace('file://', '', 1))
                        if source != destination:
                            name = self.aafm.device_path_basename(source)
                            self.add_to_queue(self.QUEUE_ACTION_MOVE_IN_DEVICE, source, os.path.join(destination, name))
        else:
            # COPY stuff
            for line in [line.strip() for line in data.split('\n')]:
                if line.startswith('file://'):
                    source = urllib.unquote(line.replace('file://', '', 1))
                    self.add_to_queue(self.QUEUE_ACTION_COPY_TO_DEVICE, source, destination)

        self.process_queue()


    def add_to_queue(self, action, src_file, dst_path):
        self.queue.append([action, src_file, dst_path])


    def process_queue(self):
        task = self.process_queue_task()
        gobject.idle_add(task.next)

    def process_queue_task(self):
        completed = 0
        self.update_progress()

        while len(self.queue) > 0:
            item = self.queue.pop()
            action, src, dst = item

            if action == self.QUEUE_ACTION_COPY_TO_DEVICE:
                self.aafm.copy_to_device(src, dst)
                self.refresh_device_files()
            if action == self.QUEUE_ACTION_COPY_FROM_DEVICE:
                self.aafm.copy_to_host(src, dst)
                self.refresh_host_files()
            elif action == self.QUEUE_ACTION_MOVE_IN_DEVICE:
                self.aafm.device_rename_item(src, dst)
                self.refresh_device_files()
            elif action == self.QUEUE_ACTION_MOVE_IN_HOST:
                shutil.move(src, dst)
                self.refresh_host_files()

            completed = completed + 1
            total = len(self.queue) + 1
            self.update_progress(completed * 1.0 / total)

            yield True

        yield False

    def refresh_devices_list(self, refreshFiles=False, defaultDevice=''):
        if not hasattr(self, 'aafm'):
            return

        self.devices_list = self.aafm.list_devices()

        self.devices_list_store.clear()
        new_active = 0
        if len(self.devices_list) > 0:
            if defaultDevice != '':
                self.aafm.set_device(defaultDevice)
            elif self.aafm.device == '':
                self.aafm.set_device(self.aafm.get_device_serial(self.devices_list[0]))

            i = 0
            for device in self.devices_list:
                self.devices_list_store.append([device])

                if defaultDevice == '':
                    if self.aafm.get_device_serial(device) == self.aafm.device:
                        new_active = i
                else:
                    if self.aafm.get_device_serial(device) == defaultDevice:
                        new_active = i

                i += 1

            if self.done:
                self.devicesList.set_sensitive(True)
        else:
            self.devicesList.set_sensitive(False)
            self.devices_list_store.append(['No devices found'])
            self.device_treeViewFile.clear_data()

        self.devicesList.set_active(new_active)

        if refreshFiles:
            glib.timeout_add(750, self.refresh_device_files)

    def reset_device(self):
        if len(self.devices_list) > 0:
            self.show_notice('Lost connection to device', True)
            glib.timeout_add(750, self.refresh_device_files)
            glib.timeout_add(5000, self.clear_notice)

    def on_change_device(self, widget):
        if widget.get_active() >= 0 and len(self.devices_list) >= (widget.get_active() + 1):
            serial = self.aafm.get_device_serial(self.devices_list[widget.get_active()])
            if serial != '' and self.aafm.device != serial:
                self.aafm.set_device(serial)
                self.device_cwd = self.device_cwd_default
                self.aafm.set_device_cwd(self.device_cwd)
                self.refresh_device_files()

    def on_toggle_host_start_dir_last(self, widget):
        self.startDirHost = 'last'

    def on_toggle_host_start_dir_specific(self, widget):
        self.startDirHost = 'specific'

    def on_change_host_start_dir_path(self, widget):
        self.startDirHostPath = widget.get_text()

    def on_toggle_device_start_dir_last(self, widget):
        self.startDirDevice = 'last'

    def on_toggle_device_start_dir_specific(self, widget):
        self.startDirDevice = 'specific'

    def on_change_device_start_dir_path(self, widget):
        self.startDirDevicePath = widget.get_text()

    def on_toggle_hidden(self, widget):
        self.showHidden = widget.get_active()

        self.refresh_host_files()
        self.refresh_device_files()

    def on_clicked_add_device(self, widget):
        self.show_add_device_dialog(
            "What is the local IP address\nof your device?",
            "Add a device by IP address",
            self.lastDeviceIP)

    def on_clicked_refresh_devices(self, widget):
        self.refresh_devices_list()

    def on_toggle_modified(self, widget):
        self.showModified = widget.get_active()

    def on_toggle_permissions(self, widget):
        self.showPermissions = widget.get_active()

    def on_toggle_owner(self, widget):
        self.showOwner = widget.get_active()

    def on_toggle_group(self, widget):
        self.showGroup = widget.get_active()

    def open_prefs(self, widget, data=None):
        if self.window_prefs is not None:
            return False  # The window is already showing

        # Build preferences window from XML
        builder_prefs = gtk.Builder()
        builder_prefs.add_from_file(os.path.join(self.basedir, "data/glade/preferences.xml"))
        builder_prefs.connect_signals({"on_window_destroy": self.destroy_prefs})

        hostDefaultLastDir = builder_prefs.get_object('hostDefaultLastDir')
        hostDefaultSpecificDir = builder_prefs.get_object('hostDefaultSpecificDir')
        deviceDefaultLastDir = builder_prefs.get_object('deviceDefaultLastDir')
        deviceDefaultSpecificDir = builder_prefs.get_object('deviceDefaultSpecificDir')

        if self.startDirHost == 'last':
            hostDefaultLastDir.set_active(True)
            hostDefaultSpecificDir.set_active(False)
        else:
            hostDefaultSpecificDir.set_active(True)
            hostDefaultLastDir.set_active(False)

        if self.startDirDevice == 'last':
            deviceDefaultLastDir.set_active(True)
            deviceDefaultSpecificDir.set_active(False)
        else:
            deviceDefaultSpecificDir.set_active(True)
            deviceDefaultLastDir.set_active(False)

        hostDefaultLastDir.connect('toggled', self.on_toggle_host_start_dir_last)
        hostDefaultSpecificDir.connect('toggled', self.on_toggle_host_start_dir_specific)
        deviceDefaultLastDir.connect('toggled', self.on_toggle_device_start_dir_last)
        deviceDefaultSpecificDir.connect('toggled', self.on_toggle_device_start_dir_specific)

        hostDefaultSpecificDirPath = builder_prefs.get_object('hostDefaultSpecificDirPath')
        hostDefaultSpecificDirPath.set_text(self.startDirHostPath)
        hostDefaultSpecificDirPath.connect('changed', self.on_change_host_start_dir_path)

        deviceDefaultSpecificDirPath = builder_prefs.get_object('deviceDefaultSpecificDirPath')
        deviceDefaultSpecificDirPath.set_text(self.startDirDevicePath)
        deviceDefaultSpecificDirPath.connect('changed', self.on_change_device_start_dir_path)

        showModified = builder_prefs.get_object('showModified')
        showModified.set_active(self.showModified)
        showModified.connect('toggled', self.on_toggle_modified)

        showPermissions = builder_prefs.get_object('showPermissions')
        showPermissions.set_active(self.showPermissions)
        showPermissions.connect('toggled', self.on_toggle_permissions)

        showOwner = builder_prefs.get_object('showOwner')
        showOwner.set_active(self.showOwner)
        showOwner.connect('toggled', self.on_toggle_owner)

        showGroup = builder_prefs.get_object('showGroup')
        showGroup.set_active(self.showGroup)
        showGroup.connect('toggled', self.on_toggle_group)

        self.window_prefs = builder_prefs.get_object("window")
        try:
            self.window_prefs.set_icon_from_file(os.path.join(self.basedir, "data/icons/aafm.svg"))
        except:
            self.window_prefs.set_icon_from_file(os.path.join(self.basedir, "data/icons/aafm.png"))

        self.window_prefs.show_all()

    def write_settings_file(self):
        try:
            with open(self.config_file_loc, 'w') as config_file:
                self.config.write(config_file)
                return True
        except IOError:
            return False

    def write_settings(self):
        self.config.set('aafm', 'lastdir_host', self.host_cwd)
        self.config.set('aafm', 'lastdir_device', self.device_cwd)
        self.config.set('aafm', 'startdir_host', self.startDirHost)
        self.config.set('aafm', 'startdir_host_path', self.startDirHostPath)
        self.config.set('aafm', 'startdir_device', self.startDirDevice)
        self.config.set('aafm', 'startdir_device_path', self.startDirDevicePath)
        self.config.set('aafm', 'show_hidden', 'yes' if self.showHidden else 'no')
        self.config.set('aafm', 'show_modified', 'yes' if self.showModified else 'no')
        self.config.set('aafm', 'show_permissions', 'yes' if self.showPermissions else 'no')
        self.config.set('aafm', 'show_owner', 'yes' if self.showOwner else 'no')
        self.config.set('aafm', 'show_group', 'yes' if self.showGroup else 'no')
        self.config.set('aafm', 'last_serial', self.lastDeviceSerial)
        self.config.set('aafm', 'last_ip', self.lastDeviceIP)

        # Set config location to home directory if we couldn't find a working path
        if self.config_file_loc == "":
            self.config_file_loc = self.config_file_loc_default

        if not self.write_settings_file():
            # Set config location to home directory if we don't have write access to the found path
            self.config_file_loc = self.config_file_loc_default
            self.write_settings_file()

    def on_keypress_add_device(self, widget, event):
        if event.keyval == 65293:
            self.dialogWindow.emit('response', gtk.RESPONSE_OK)

    def on_response_add_device(self, widget, response):
        device_network_path = self.dialogEntry.get_text()

        self.dialogWindow.destroy()
        if (response == gtk.RESPONSE_OK) and device_network_path is not None:
            device_network_path = device_network_path.strip()
            if device_network_path.strip() != '':
                self.lastDeviceIP = device_network_path
                connected = string.join(self.aafm.execute('%s connect %s' % (self.aafm.adb, device_network_path)))
                print 'Connection response: %s' % connected
                if 'already connected to' in connected:
                    self.refresh_devices_list()
                    self.show_notice('Already connected to %s' % device_network_path, True)
                    glib.timeout_add(2000, self.clear_notice)
                elif 'connected to' in connected:
                    self.show_notice('Connected to %s' % device_network_path)
                    glib.timeout_add(150, lambda: self.refresh_devices_list(True))
                    glib.timeout_add(2000, self.clear_notice)
                else:
                    self.show_notice('Unable to connect to %s' % device_network_path, True)
                    glib.timeout_add(5000, self.clear_notice)

    def show_add_device_dialog(self, message, title='', default_text=''):
        # Returns user input as a string or None
        # If user does not input text it returns None, NOT AN EMPTY STRING.
        self.dialogWindow = gtk.MessageDialog(self.window,
                                              gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                                              gtk.MESSAGE_QUESTION,
                                              gtk.BUTTONS_OK_CANCEL,
                                              message)

        self.dialogWindow.set_title(title)
        self.dialogWindow.set_icon_name('')

        dialogBox = self.dialogWindow.get_content_area()
        self.dialogEntry = gtk.Entry()
        self.dialogEntry.set_text(default_text if default_text is not None else '')
        self.dialogEntry.connect('key-press-event', self.on_keypress_add_device)
        dialogBox.pack_end(self.dialogEntry, False, False, 0)

        self.dialogWindow.connect('response', self.on_response_add_device)
        self.dialogWindow.show_all()
        self.dialogWindow.run()

    def die_callback(self, widget, data=None):
        self.destroy(widget, data)


    def destroy_prefs(self, widget, data=None):
        self.window_prefs = None

    def destroy(self, widget, data=None):
        self.write_settings()
        gtk.main_quit()

    def main(self):
        gtk.main()


if __name__ == '__main__':
    gui = Aafm_GUI()
    gui.main()

