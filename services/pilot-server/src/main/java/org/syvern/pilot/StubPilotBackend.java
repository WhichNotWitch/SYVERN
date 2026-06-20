package org.syvern.pilot;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Deterministic stub backend. It mirrors the Python {@code PilotStubAdapter}
 * (src/syvern/adapters/stub.py): magic markers drive the stage gates and a
 * regex extracts elements. This makes the service runnable and behaviourally
 * equivalent to the in-repo stub, so SYVERN can be pointed at it end-to-end
 * before the real Pilot is wired.
 *
 * <p>It does NOT understand SysML v2. Replace with {@link RealPilotBackend}.
 */
public final class StubPilotBackend implements PilotBackend {

    private static final String VERSION = "stub-0.1.0";

    private static final Pattern ELEMENT = Pattern.compile(
            "\\b(part|attribute|connection|requirement|item|action)\\s+([A-Za-z0-9_.-]+)",
            Pattern.CASE_INSENSITIVE);

    @Override
    public Api.AnalysisResult analyze(String text) {
        String normalized = text == null ? "" : text.trim().replaceAll("\\s+", " ");
        String lower = normalized.toLowerCase();

        Api.ParseStage parse;
        List<Api.Element> elements;
        if (normalized.isEmpty()) {
            parse = new Api.ParseStage(false, List.of(diag("PARSE_EMPTY_INPUT", "Input text is empty")));
            elements = List.of();
        } else if (lower.contains("syntax_error")) {
            parse = new Api.ParseStage(false, List.of(diag("PARSE_SYNTAX_ERROR", "Synthetic syntax error marker")));
            elements = List.of();
        } else {
            parse = new Api.ParseStage(true, List.of());
            elements = extractElements(normalized);
        }

        Api.ResolveStage resolve = lower.contains("unresolved_ref")
                ? new Api.ResolveStage(false, 1,
                        List.of(diag("RESOLVE_UNRESOLVED_REF", "Synthetic unresolved reference marker")))
                : new Api.ResolveStage(true, 0, List.of());

        Api.TypecheckStage typecheck = lower.contains("type_error")
                ? new Api.TypecheckStage(false, 1,
                        List.of(diag("TYPECHECK_ERROR", "Synthetic type error marker")))
                : new Api.TypecheckStage(true, 0, List.of());

        return new Api.AnalysisResult(parse, resolve, typecheck, elements, VERSION);
    }

    @Override
    public Api.Version version() {
        return new Api.Version(VERSION, "sysml-v2-textual-stub", "rules-stub");
    }

    private static List<Api.Element> extractElements(String text) {
        List<Api.Element> out = new ArrayList<>();
        Matcher matcher = ELEMENT.matcher(text);
        while (matcher.find()) {
            out.add(new Api.Element(matcher.group(1).toLowerCase(), matcher.group(2).toLowerCase()));
        }
        return out;
    }

    private static Api.Diagnostic diag(String code, String message) {
        return new Api.Diagnostic(code, message, null);
    }
}
