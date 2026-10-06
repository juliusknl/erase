#import <Cocoa/Cocoa.h>

@interface EraseDelegate : NSObject <NSApplicationDelegate>
@property(strong) NSTask *backend;
@property(strong) NSPipe *errors;
@property BOOL quitting;
@end

@implementation EraseDelegate
- (void)openDashboard:(id)sender {
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"http://127.0.0.1:8787/"]];
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSMenu *menu = [[NSMenu alloc] init];
    NSMenuItem *root = [[NSMenuItem alloc] init];
    [menu addItem:root];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"erase"];
    [appMenu addItemWithTitle:@"Open dashboard" action:@selector(openDashboard:) keyEquivalent:@"o"];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:@"Quit erase" action:@selector(terminate:) keyEquivalent:@"q"];
    root.submenu = appMenu;
    NSApp.mainMenu = menu;

    NSString *resources = NSBundle.mainBundle.resourcePath;
    self.backend = [[NSTask alloc] init];
    self.backend.executableURL = [NSURL fileURLWithPath:[resources stringByAppendingPathComponent:@"python/bin/python3"]];
    self.backend.arguments = @[@"-I", @"-B", [resources stringByAppendingPathComponent:@"app/scripts/desktop_entry.py"],
                              @"--root", [resources stringByAppendingPathComponent:@"app"]];
    self.backend.standardOutput = [NSFileHandle fileHandleWithNullDevice];
    self.errors = [NSPipe pipe];
    self.backend.standardError = self.errors;
    // Drain the pipe continuously so a background diagnostic cannot block sends.
    NSMutableData *errorText = [NSMutableData data];
    self.errors.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *chunk = handle.availableData;
        @synchronized (errorText) {
            if (errorText.length < 8192 && chunk.length) {
                [errorText appendData:[chunk subdataWithRange:NSMakeRange(0, MIN(chunk.length, 8192-errorText.length))]];
            }
        }
    };
    __weak EraseDelegate *weakSelf = self;
    self.backend.terminationHandler = ^(NSTask *task) {
        dispatch_async(dispatch_get_main_queue(), ^{
            EraseDelegate *owner = weakSelf;
            if (owner.quitting) { [NSApp replyToApplicationShouldTerminate:YES]; return; }
            if (task.terminationStatus != 0) {
                NSAlert *alert = [[NSAlert alloc] init];
                alert.messageText = @"erase couldn’t start";
                NSString *detail;
                @synchronized (errorText) { detail = [[NSString alloc] initWithData:errorText encoding:NSUTF8StringEncoding]; }
                alert.informativeText = detail.length ? detail : @"Reopen erase to try again. Your saved data and keys have been kept.";
                [alert addButtonWithTitle:@"OK"];
                [NSApp activateIgnoringOtherApps:YES];
                [alert runModal];
            }
            [NSApp terminate:nil];
        });
    };
    NSError *error;
    if (![self.backend launchAndReturnError:&error]) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"The erase download is incomplete";
        alert.informativeText = @"Download a fresh copy and reopen it. Your existing data stays on this Mac.";
        [alert runModal];
        [NSApp terminate:nil];
    }
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)visible {
    [self openDashboard:nil];
    return YES;
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (self.backend.running) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"Close the launcher?";
        alert.informativeText = @"erase may already be running in the background. Pause sending from the dashboard.";
        [alert addButtonWithTitle:@"Continue opening"];
        [alert addButtonWithTitle:@"Close launcher"];
        if ([alert runModal] == NSAlertFirstButtonReturn) return NSTerminateCancel;
        self.quitting = YES;
        [self.backend terminate];
        return NSTerminateLater;
    }
    return NSTerminateNow;
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        EraseDelegate *delegate = [[EraseDelegate alloc] init];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app run];
    }
    return 0;
}
