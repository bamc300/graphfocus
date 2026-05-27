local M = {}
local users = require("users")
local json = require("cjson")

function M.find(id)
  return users.get(id)
end

function M.create(name)
  local id = generate_id()
  users.save(id, name)
  return id
end

local function generate_id()
  return "x"
end

local function plain_helper(a, b)
  return a + b
end

return M
