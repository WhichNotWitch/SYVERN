package org.syvern.pilot;

import org.eclipse.emf.ecore.EObject;
import org.eclipse.xtext.validation.Issue;
import org.omg.sysml.interactive.SysMLInteractive;
import org.omg.sysml.interactive.SysMLInteractiveResult;
import org.omg.sysml.lang.sysml.Element;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * Real backend over the official SysML v2 Pilot via {@code SysMLInteractive}
 * (the same entry point the Jupyter kernel uses). Verified against
 * jupyter-sysml-kernel 0.59.0.
 *
 * <p>Lifecycle: one resident instance loads the standard library once
 * ({@code SYSML_LIBRARY_PATH}); each request clears the previous user resource,
 * runs {@code process(text)}, and maps the structured result:
 * <ul>
 *   <li>{@code getSyntaxErrors()}            -> parse</li>
 *   <li>semantic errors, code contains "Linking" -> resolve (unresolved refs)</li>
 *   <li>remaining semantic errors            -> typecheck (KerML/SysML constraints)</li>
 *   <li>{@code getRootElement().eAllContents()} -> elements (user model only,
 *       library excluded)</li>
 * </ul>
 * {@code SysMLInteractive} is stateful, so {@link #analyze} is synchronized.
 */
public final class RealPilotBackend implements PilotBackend {

    private static final String VERSION =
            System.getenv().getOrDefault("PILOT_VERSION", "pilot-0.59.0");

    private final SysMLInteractive sysml;

    public RealPilotBackend() {
        this.sysml = SysMLInteractive.createInstance();
        String libraryPath = System.getenv("SYSML_LIBRARY_PATH");
        if (libraryPath != null && !libraryPath.isBlank()) {
            this.sysml.loadLibrary(libraryPath);
        }
    }

    @Override
    public synchronized Api.AnalysisResult analyze(String text) {
        try {
            sysml.removeResource();
        } catch (Exception ignore) {
            // no current resource to remove
        }

        SysMLInteractiveResult result;
        try {
            result = sysml.process(text);
        } catch (Exception e) {
            return new Api.AnalysisResult(
                    new Api.ParseStage(false, List.of(
                            new Api.Diagnostic("PILOT_PROCESS_ERROR", String.valueOf(e.getMessage()), null))),
                    new Api.ResolveStage(false, 0, List.of()),
                    new Api.TypecheckStage(false, 0, List.of()),
                    List.of(),
                    VERSION);
        }

        List<Api.Diagnostic> syntax = new ArrayList<>();
        for (Issue issue : result.getSyntaxErrors()) {
            syntax.add(diagnostic("PILOT_SYNTAX_ERROR", issue));
        }

        List<Api.Diagnostic> resolveErrors = new ArrayList<>();
        List<Api.Diagnostic> typeErrors = new ArrayList<>();
        for (Issue issue : result.getSemanticErrors()) {
            if (String.valueOf(issue.getCode()).contains("Linking")) {
                resolveErrors.add(diagnostic("PILOT_UNRESOLVED_REF", issue));
            } else {
                typeErrors.add(diagnostic("PILOT_TYPECHECK_ERROR", issue));
            }
        }

        List<Api.Element> elements = extractElements(result.getRootElement());

        return new Api.AnalysisResult(
                new Api.ParseStage(syntax.isEmpty(), syntax),
                new Api.ResolveStage(resolveErrors.isEmpty(), resolveErrors.size(), resolveErrors),
                new Api.TypecheckStage(typeErrors.isEmpty(), typeErrors.size(), typeErrors),
                elements,
                VERSION);
    }

    @Override
    public Api.Version version() {
        return new Api.Version(VERSION, "sysml-v2-textual", "kerml-sysml-constraints");
    }

    private static List<Api.Element> extractElements(Element root) {
        List<Api.Element> elements = new ArrayList<>();
        if (root == null) {
            return elements;
        }
        // Traverse from the user's root element only — the loaded library is in
        // the same ResourceSet but is not contained under this root.
        for (Iterator<EObject> it = root.eAllContents(); it.hasNext(); ) {
            EObject object = it.next();
            if (!(object instanceof Element element)) {
                continue;
            }
            String type = typeOf(object);
            if (type == null) {
                continue;
            }
            String qualifiedName = element.getQualifiedName();
            if (qualifiedName == null || qualifiedName.isBlank()) {
                continue;
            }
            elements.add(new Api.Element(type, qualifiedName.toLowerCase()));
        }
        return elements;
    }

    private static final List<String> ELEMENT_TYPES = List.of(
            "part", "attribute", "connection", "requirement", "action", "state",
            "transition", "item", "port", "interface", "constraint", "calc", "flow");

    private static String typeOf(EObject object) {
        String metaclass = object.eClass().getName().toLowerCase();
        for (String type : ELEMENT_TYPES) {
            if (metaclass.startsWith(type)) {
                return type;
            }
        }
        return null;
    }

    private static Api.Diagnostic diagnostic(String code, Issue issue) {
        Integer line = issue.getLineNumber();
        String location = (line != null && line >= 0) ? "line:" + line : null;
        return new Api.Diagnostic(code, issue.getMessage(), location);
    }
}
