use zed_extension_api::{self as zed, Result};

struct Dyn {}

impl zed::Extension for Dyn {
    fn new() -> Self {
        Self {}
    }
    fn language_server_command(
        &mut self,
        _: &zed::LanguageServerId,
        _: &zed::Worktree,
    ) -> Result<zed::Command> {
        Ok(zed::Command {
            command: "/home/mdray/17robots/dyn/build/dyn".to_string(),
            args: vec!["lsp".to_string()],
            env: vec![],
        })
    }
}

zed::register_extension!(Dyn);
