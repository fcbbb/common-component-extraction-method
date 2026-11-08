"""Java method-entry observations from the JDK debugging interface."""

import re

from ..runtime import prepare_workspace, write_driver


OBSERVER = r'''
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.io.*;
import java.util.*;
public class TraceRunner {
  public static void main(String[] args) throws Exception {
    LaunchingConnector connector = Bootstrap.virtualMachineManager().defaultConnector();
    Map<String, Connector.Argument> config = connector.defaultArguments();
    config.get("main").setValue(args[0]);
    config.get("options").setValue("-cp /work/classes");
    VirtualMachine vm = connector.launch(config);
    MethodEntryRequest request = vm.eventRequestManager().createMethodEntryRequest();
    request.addClassExclusionFilter("java.*");
    request.addClassExclusionFilter("jdk.*");
    request.addClassExclusionFilter("sun.*");
    request.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
    request.enable();
    Thread out = new Thread(() -> { try { vm.process().getInputStream().transferTo(System.out); } catch (IOException e) {} });
    Thread err = new Thread(() -> { try { vm.process().getErrorStream().transferTo(System.err); } catch (IOException e) {} });
    out.start(); err.start();
    try (PrintWriter trace = new PrintWriter("/work/trace.log")) {
      boolean running = true;
      while (running) {
        EventSet events = vm.eventQueue().remove();
        for (Event event : events) {
          if (event instanceof MethodEntryEvent) {
            Method method = ((MethodEntryEvent) event).method();
            trace.println(method.declaringType().name() + "." + method.name() + "|" + String.join(",", method.argumentTypeNames()));
            trace.flush();
          }
          if (event instanceof VMDeathEvent || event instanceof VMDisconnectEvent) running = false;
        }
        events.resume();
      }
    } catch (VMDisconnectedException e) {}
    int status = vm.process().waitFor();
    out.join(); err.join();
    System.exit(status);
  }
}
'''


def prepare_smoke(backend, artifact, case, workspace):
    metadata = prepare_workspace(backend, artifact, case, workspace)
    resolved = backend.resolve_entrypoints(artifact)
    main = case.metadata.get("main_class", "Smoke")
    if not isinstance(main, str) or not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", main):
        raise ValueError("invalid Java main class")
    if artifact.runtime:
        raise ValueError("Java artifacts may not supply compiler or JVM commands")
    targets = {}
    for name, unit in resolved.items():
        symbol = unit.qualified_name if unit.kind == "method" else unit.qualified_name + ".<init>"
        if unit.kind == "constructor":
            symbol = unit.parent_qualified_name + ".<init>"
        targets[name] = (symbol, unit.metadata["parameter_types"], unit.kind == "class")
    sources = ["/artifact/" + f.path for f in artifact.files if f.path.endswith(".java")]
    sources += ["/smoke/" + f.path for f in case.files if f.path.endswith(".java")]
    (workspace / "driver/TraceRunner.java").write_text(OBSERVER, encoding="utf-8")
    body = f'''report['toolchain']['compiler'] = command(['javac', '-version'], 'compiler-version')
command(['javac', '-g', '-d', '/work/classes'] + {sources!r}, 'component-build')
command(['javac', '--add-modules', 'jdk.jdi', '-d', '/work/observer', '/driver/TraceRunner.java'], 'observer-build')
command(['java', '--add-modules', 'jdk.jdi', '-cp', '/work/observer', 'TraceRunner', {main!r}], 'smoke')
trace = pathlib.Path('/work/trace.log')
observed = []
for line in trace.read_text().splitlines() if trace.exists() else []:
    symbol, _, parameters = line.partition('|')
    observed.append((symbol, [p.rsplit('.', 1)[-1] for p in parameters.split(',')] if parameters else []))
targets = {targets!r}
report['executed'] = [name for name, (symbol, parameters, any_constructor) in targets.items()
                      if any(s == symbol and (any_constructor or p == parameters) for s, p in observed)]
report['trace_method_count'] = len(observed)
'''
    return write_driver(workspace, metadata, body, evidence_level="jdk_method_entry_events")
