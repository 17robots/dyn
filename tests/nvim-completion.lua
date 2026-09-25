-- Exercise Neovim's real completion/highlighting request sequence while typing.
-- Run: nvim --clean --headless -c 'luafile tests/nvim-completion.lua'
if not vim.lsp.completion or not vim.lsp.completion.enable then
  if vim.env.DYN_REQUIRE_ALL == '1' then
    io.stderr:write('Neovim 0.11+ required for release completion checks\n')
    vim.cmd('cquit 1')
    return
  end
  print('Neovim completion test skipped: built-in completion requires Neovim 0.11+')
  vim.cmd('qa!')
  return
end
local root = vim.fn.tempname()
vim.fn.mkdir(root, 'p')
vim.cmd.edit(root .. '/main.dyn')
vim.bo.filetype = 'dyn'
vim.o.completeopt = 'menu,menuone,noselect,popup'
local client
local finished = false
local function finish(message)
  if finished then return end
  finished = true
  if client then client:stop(true) end
  vim.fn.delete(root, 'rf')
  if message then
    io.stderr:write(message .. '\n')
    vim.cmd('cquit 1')
  else
    print('Neovim import completion passed')
    vim.cmd('qa!')
  end
end
local function words()
  local result = {}
  for _, item in ipairs(vim.fn.complete_info({'items'}).items) do
    result[item.word] = true
  end
  return result
end
local function await_items(expected, next_step)
  local deadline = vim.uv.hrtime() + 5e9
  local function poll()
    if finished then return end
    local present = words()
    local ready = true
    for _, word in ipairs(expected) do ready = ready and present[word] end
    if ready then next_step()
    elseif not client or client:is_stopped() then finish('Dyn LSP stopped during import completion')
    elseif vim.uv.hrtime() > deadline then
      finish('Missing completion items: ' .. table.concat(expected, ', ') .. '; buffer: ' .. vim.api.nvim_get_current_line())
    else vim.defer_fn(poll, 25) end
  end
  vim.defer_fn(poll, 25)
end
vim.lsp.start({
  name = 'dyn',
  cmd = {vim.env.DYN or (vim.fn.getcwd() .. '/build/dyn'), 'lsp'},
  root_dir = root,
  on_init = function(attached)
    client = attached
    vim.lsp.completion.enable(true, client.id, 0, {autotrigger = true})
    vim.api.nvim_input('iuse "')
    await_items({'std', 'vendor'}, function()
      local function accept(word, done)
        local info = vim.fn.complete_info({'items', 'selected'})
        local target
        for index, item in ipairs(info.items) do if item.word == word then target = index - 1 end end
        if not target then return finish('No selectable item: ' .. word) end
        local steps = (target - info.selected) % (#info.items + 1)
        vim.api.nvim_input(string.rep('<C-n>', steps) .. '<C-y>')
        vim.defer_fn(done, 100)
      end
      accept('std', function()
        if vim.api.nvim_get_current_line() ~= 'use "std' then return finish('std acceptance inserted unexpected text') end
        vim.api.nvim_input('/')
        await_items({'io', 'mem', 'net'}, function()
          accept('net', function()
            if vim.api.nvim_get_current_line() ~= 'use "std/net' then return finish('net acceptance inserted unexpected text') end
            vim.api.nvim_input('/')
            await_items({'http', 'tls', 'dns'}, function() finish() end)
          end)
        end)
      end)
    end)
  end,
})
vim.defer_fn(function() finish('Neovim completion test timed out') end, 15000)
