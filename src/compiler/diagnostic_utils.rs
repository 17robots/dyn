use std::collections::BTreeSet;
use std::path::Path;

use crate::compiler::diagnostics::Diagnostic;

pub fn sort_diagnostics_by_primary_path(diagnostics: &mut [Diagnostic]) {
    diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });
}

pub fn dedupe_diagnostics_by_primary_span(diagnostics: &mut Vec<Diagnostic>) {
    let mut seen = BTreeSet::new();
    diagnostics.retain(|diagnostic| {
        let primary_label = diagnostic.labels.first();
        let path = primary_label
            .map(|label| normalize_diagnostic_path(&label.file_path))
            .unwrap_or_default();
        let span = primary_label.and_then(|label| {
            label.span.map(|span| {
                (
                    span.start_byte,
                    span.end_byte,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                )
            })
        });
        let key = (
            diagnostic.phase,
            diagnostic.code,
            diagnostic.message.clone(),
            path,
            span,
        );
        seen.insert(key)
    });
}

pub fn normalize_diagnostic_path(path: &Path) -> String {
    let mut normalized = path.to_string_lossy().replace('\\', "/");
    while normalized.starts_with("./") {
        normalized = normalized[2..].to_string();
    }
    normalized
}
