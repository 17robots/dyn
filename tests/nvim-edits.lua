-- Real editor client: imports/constants, diagnostic recovery and semantic ranges.
local root = vim.fn.tempname()
vim.fn.mkdir(root, 'p')
vim.cmd.edit(root .. '/main.dyn')
vim.bo.filetype = 'dyn'
local bufnr = vim.api.nvim_get_current_buf()
local client
local done = false
local publications = 0
local function finish(error)
  if done then return end
  done = true
  if client then client:stop(true) end
  vim.fn.delete(root, 'rf')
  if error then
    io.stderr:write(tostring(error) .. '\n')
    vim.cmd('cquit 1')
  else
    print('Neovim import/const edits, diagnostics and semantic highlights passed')
    vim.cmd('qa!')
  end
end
local lines = {
  'use "std/mem" mem',
  'const Answer: i32 = 42',
  'fn main() { value := mem.Arena{} _ = value _ = Answer }',
}
vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
local function run()
  vim.treesitter.language.add('dyn', {path = assert(vim.env.DYN_NVIM_PARSER)})
  local query = vim.treesitter.query.parse('dyn', table.concat(vim.fn.readfile('tree-sitter-dyn/neovim/highlights.scm'), '\n'))
  local parser = vim.treesitter.get_parser(bufnr, 'dyn')
  vim.treesitter.start(bufnr, 'dyn')
  local function errors()
    return vim.diagnostic.get(bufnr, {severity = vim.diagnostic.severity.ERROR})
  end
  local function request(method)
    local result, error = client:request_sync(method,
      {textDocument = {uri = vim.uri_from_bufnr(bufnr)}}, 5000, bufnr)
    assert(result and not result.err and not error, vim.inspect(result or error))
    return result.result
  end
  local function edit(row, text, want_error)
    local previous = publications
    vim.api.nvim_buf_set_lines(bufnr, row, row + 1, false, {text})
    -- Flush Neovim's pending didChange before the barrier request.
    request('textDocument/documentSymbol')
    assert(vim.wait(5000, function()
      return publications > previous and (#errors() > 0) == want_error
    end, 20), 'Diagnostic publication did not match edit: ' .. text)
  end
  assert(vim.wait(5000, function() return publications > 0 end, 20), 'No initial diagnostics')
  assert(#errors() == 0, vim.inspect(errors()))
  local function highlights()
    local result = request('textDocument/semanticTokens/full')
    assert(result and result.data and #result.data > 0, 'No semantic tokens')
    local row, col = 0, 0
    local answer = false
    local current = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
    for index = 1, #result.data, 5 do
      local dr, dc, length = unpack(result.data, index, index + 2)
      if dr == 0 then col = col + dc else row = row + dr col = dc end
      assert(current[row + 1] and col + length <= #current[row + 1], 'Stale highlight range')
      if current[row + 1]:sub(col + 1, col + length) == 'Answer' then answer = true end
    end
    assert(answer, 'Constant lost semantic highlighting')
    local tree = parser:parse()[1]
    local captured = {}
    for id, node in query:iter_captures(tree:root(), bufnr, 0, -1) do
      captured[query.captures[id] .. ':' .. vim.treesitter.get_node_text(node, bufnr)] = true
    end
    for _, capture in ipairs({'keyword:use', 'namespace:mem', 'constant:Answer', 'string:"std/mem"'}) do
      assert(captured[capture], 'Missing Tree-sitter highlight: ' .. capture)
    end
  end
  highlights()
  for _ = 1, 3 do
    edit(1, 'const Answer: i32 = true', true)
    local found = false
    for _, diagnostic in ipairs(errors()) do
      if diagnostic.lnum == 1 then found = true end
    end
    assert(found, 'Constant error attached to wrong line')
    edit(1, lines[2], false)
    edit(0, 'use "std/not_a_package" mem', true)
    edit(0, lines[1], false)
    highlights()
  end
  -- Line insertion must shift all highlight positions and clear stale diagnostics.
  vim.api.nvim_buf_set_lines(bufnr, 0, 0, false, {'// shifted import and constant'})
  request('textDocument/documentSymbol')
  highlights()
end
vim.lsp.start({
  name = 'dyn',
  cmd = {vim.env.DYN or (vim.fn.getcwd() .. '/build/dyn'), 'lsp'},
  root_dir = root,
  handlers = {
    ['textDocument/publishDiagnostics'] = function(error, result, context, config)
      publications = publications + 1
      vim.lsp.handlers['textDocument/publishDiagnostics'](error, result, context, config)
    end,
  },
  on_attach = function(attached)
    client = attached
    vim.schedule(function()
      local ok, error = xpcall(run, debug.traceback)
      finish(not ok and error or nil)
    end)
  end,
})
vim.defer_fn(function() finish('Neovim edit test timed out') end, 30000)
