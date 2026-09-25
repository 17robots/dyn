-- Neovim setup for the dyn language.
-- 1) Filetype detection
vim.filetype.add({ extension = { dyn = "dyn" } })

-- 2) Register the parser with nvim-treesitter
--    Queries: link or copy tree-sitter-dyn/queries/*.scm into a runtimepath
--    dir as queries/dyn/*.scm (e.g. ~/.config/nvim/queries/dyn/).
local parser_config = require("nvim-treesitter.parsers").get_parser_configs()
parser_config.dyn = {
  install_info = {
    url = "/path/to/tree-sitter-dyn", -- local checkout, or a git URL
    files = { "src/parser.c" },
    branch = "main",
    generate_requires_npm = false,
    requires_generate_from_grammar = false,
  },
  filetype = "dyn",
}
-- Then run :TSInstall dyn

-- 3) Comment string for plugins like Comment.nvim / native gc
vim.api.nvim_create_autocmd("FileType", {
  pattern = "dyn",
  callback = function()
    vim.bo.commentstring = "// %s"
    vim.bo.shiftwidth = 4
    vim.bo.expandtab = true
  end,
})
