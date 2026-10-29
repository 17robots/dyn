#include "shader.h"
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif
typedef struct Host {
  VkInstance instance;
  VkPhysicalDevice physical;
  VkDevice device;
  VkQueue queue;
  VkPhysicalDeviceProperties properties;
  VkPhysicalDeviceMemoryProperties memories;
  uint32_t family;
  VkDescriptorSetLayout set_layout;
  VkDescriptorPool descriptors;
  VkDescriptorSet set;
  VkPipelineLayout layout;
  VkPipeline pipeline;
  VkCommandPool pool;
  VkCommandBuffer command;
  VkFence fence;
  VkBuffer buffer;
  VkDeviceMemory memory;
  void *mapped;
  VkDeviceSize capacity;
  int coherent;
} Host;
EXPORT void dyn_ui_vk_close(void *p) {
  Host *h = p;
  if (!h)
    return;
  if (h->device) {
    vkDeviceWaitIdle(h->device);
    if (h->mapped)
      vkUnmapMemory(h->device, h->memory);
    if (h->buffer)
      vkDestroyBuffer(h->device, h->buffer, NULL);
    if (h->memory)
      vkFreeMemory(h->device, h->memory, NULL);
    if (h->fence)
      vkDestroyFence(h->device, h->fence, NULL);
    if (h->pool)
      vkDestroyCommandPool(h->device, h->pool, NULL);
    if (h->pipeline)
      vkDestroyPipeline(h->device, h->pipeline, NULL);
    if (h->layout)
      vkDestroyPipelineLayout(h->device, h->layout, NULL);
    if (h->descriptors)
      vkDestroyDescriptorPool(h->device, h->descriptors, NULL);
    if (h->set_layout)
      vkDestroyDescriptorSetLayout(h->device, h->set_layout, NULL);
    vkDestroyDevice(h->device, NULL);
  }
  if (h->instance)
    vkDestroyInstance(h->instance, NULL);
  free(h);
}
static int extension(VkPhysicalDevice physical, const char *name) {
  uint32_t count = 0;
  VkResult result =
      physical
          ? vkEnumerateDeviceExtensionProperties(physical, NULL, &count, NULL)
          : vkEnumerateInstanceExtensionProperties(NULL, &count, NULL);
  if (result != VK_SUCCESS || !count)
    return 0;
  VkExtensionProperties *items = calloc(count, sizeof(*items));
  if (!items)
    return 0;
  result =
      physical
          ? vkEnumerateDeviceExtensionProperties(physical, NULL, &count, items)
          : vkEnumerateInstanceExtensionProperties(NULL, &count, items);
  int found = 0;
  if (result == VK_SUCCESS)
    for (uint32_t i = 0; i < count; ++i)
      if (!strcmp(items[i].extensionName, name)) {
        found = 1;
        break;
      }
  free(items);
  return found;
}
EXPORT void *dyn_ui_vk_open(void) {
  Host *h = calloc(1, sizeof(*h));
  if (!h)
    return NULL;
  VkInstanceCreateInfo instance = {.sType =
                                       VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
  const char *portability = "VK_KHR_portability_enumeration";
  if (extension(VK_NULL_HANDLE, portability)) {
    instance.flags |= VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR;
    instance.enabledExtensionCount = 1;
    instance.ppEnabledExtensionNames = &portability;
  }
  if (vkCreateInstance(&instance, NULL, &h->instance) != VK_SUCCESS)
    goto fail;
  uint32_t count = 0;
  if (vkEnumeratePhysicalDevices(h->instance, &count, NULL) != VK_SUCCESS ||
      !count)
    goto fail;
  VkPhysicalDevice *devices = calloc(count, sizeof(*devices));
  if (!devices)
    goto fail;
  if (vkEnumeratePhysicalDevices(h->instance, &count, devices) != VK_SUCCESS) {
    free(devices);
    goto fail;
  }
  for (uint32_t i = 0; i < count && !h->physical; ++i) {
    uint32_t families = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &families, NULL);
    VkQueueFamilyProperties *props = calloc(families, sizeof(*props));
    if (!props) {
      free(devices);
      goto fail;
    }
    vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &families, props);
    for (uint32_t q = 0; q < families; ++q)
      if (props[q].queueCount && (props[q].queueFlags & VK_QUEUE_COMPUTE_BIT)) {
        h->physical = devices[i];
        h->family = q;
        break;
      }
    free(props);
  }
  free(devices);
  if (!h->physical)
    goto fail;
  vkGetPhysicalDeviceProperties(h->physical, &h->properties);
  vkGetPhysicalDeviceMemoryProperties(h->physical, &h->memories);
  float priority = 1;
  VkDeviceQueueCreateInfo queue = {
      .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
      .queueFamilyIndex = h->family,
      .queueCount = 1,
      .pQueuePriorities = &priority};
  VkDeviceCreateInfo device = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                               .queueCreateInfoCount = 1,
                               .pQueueCreateInfos = &queue};
  const char *subset = "VK_KHR_portability_subset";
  if (extension(h->physical, subset)) {
    device.enabledExtensionCount = 1;
    device.ppEnabledExtensionNames = &subset;
  }
  if (vkCreateDevice(h->physical, &device, NULL, &h->device) != VK_SUCCESS)
    goto fail;
  vkGetDeviceQueue(h->device, h->family, 0, &h->queue);
  VkDescriptorSetLayoutBinding binding = {
      .binding = 0,
      .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
      .descriptorCount = 1,
      .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
  VkDescriptorSetLayoutCreateInfo set_layout = {
      .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
      .bindingCount = 1,
      .pBindings = &binding};
  if (vkCreateDescriptorSetLayout(h->device, &set_layout, NULL,
                                  &h->set_layout) != VK_SUCCESS)
    goto fail;
  VkDescriptorPoolSize pool_size = {.type = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                                    .descriptorCount = 1};
  VkDescriptorPoolCreateInfo descriptors = {
      .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
      .maxSets = 1,
      .poolSizeCount = 1,
      .pPoolSizes = &pool_size};
  if (vkCreateDescriptorPool(h->device, &descriptors, NULL, &h->descriptors) !=
      VK_SUCCESS)
    goto fail;
  VkDescriptorSetAllocateInfo set = {
      .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
      .descriptorPool = h->descriptors,
      .descriptorSetCount = 1,
      .pSetLayouts = &h->set_layout};
  if (vkAllocateDescriptorSets(h->device, &set, &h->set) != VK_SUCCESS)
    goto fail;
  VkPipelineLayoutCreateInfo layout = {
      .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
      .setLayoutCount = 1,
      .pSetLayouts = &h->set_layout};
  if (vkCreatePipelineLayout(h->device, &layout, NULL, &h->layout) !=
      VK_SUCCESS)
    goto fail;
  VkShaderModule module = VK_NULL_HANDLE;
  VkShaderModuleCreateInfo shader = {
      .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
      .codeSize = sizeof(dyn_ui_shader),
      .pCode = dyn_ui_shader};
  if (vkCreateShaderModule(h->device, &shader, NULL, &module) != VK_SUCCESS)
    goto fail;
  VkComputePipelineCreateInfo pipeline = {
      .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
      .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                .module = module,
                .pName = "main"},
      .layout = h->layout};
  VkResult status = vkCreateComputePipelines(h->device, VK_NULL_HANDLE, 1,
                                             &pipeline, NULL, &h->pipeline);
  vkDestroyShaderModule(h->device, module, NULL);
  if (status != VK_SUCCESS)
    goto fail;
  VkCommandPoolCreateInfo pool = {
      .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
      .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
      .queueFamilyIndex = h->family};
  if (vkCreateCommandPool(h->device, &pool, NULL, &h->pool) != VK_SUCCESS)
    goto fail;
  VkCommandBufferAllocateInfo command = {
      .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
      .commandPool = h->pool,
      .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
      .commandBufferCount = 1};
  if (vkAllocateCommandBuffers(h->device, &command, &h->command) != VK_SUCCESS)
    goto fail;
  VkFenceCreateInfo fence = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  if (vkCreateFence(h->device, &fence, NULL, &h->fence) != VK_SUCCESS)
    goto fail;
  return h;
fail:
  dyn_ui_vk_close(h);
  return NULL;
}
static int storage(Host *h, VkDeviceSize bytes) {
  if (bytes <= h->capacity)
    return 1;
  if (h->mapped) {
    vkUnmapMemory(h->device, h->memory);
    h->mapped = NULL;
  }
  if (h->buffer) {
    vkDestroyBuffer(h->device, h->buffer, NULL);
    h->buffer = VK_NULL_HANDLE;
  }
  if (h->memory) {
    vkFreeMemory(h->device, h->memory, NULL);
    h->memory = VK_NULL_HANDLE;
  }
  h->capacity = 0;
  VkBufferCreateInfo buffer = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                               .size = bytes,
                               .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
                               .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
  if (vkCreateBuffer(h->device, &buffer, NULL, &h->buffer) != VK_SUCCESS)
    return 0;
  VkMemoryRequirements requirements;
  vkGetBufferMemoryRequirements(h->device, h->buffer, &requirements);
  uint32_t index = UINT32_MAX;
  for (uint32_t i = 0; i < h->memories.memoryTypeCount; ++i)
    if ((requirements.memoryTypeBits & (1u << i)) &&
        (h->memories.memoryTypes[i].propertyFlags &
         VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)) {
      index = i;
      if (h->memories.memoryTypes[i].propertyFlags &
          VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)
        break;
    }
  if (index == UINT32_MAX)
    return 0;
  h->coherent = (h->memories.memoryTypes[index].propertyFlags &
                 VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) != 0;
  VkMemoryAllocateInfo memory = {.sType =
                                     VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                                 .allocationSize = requirements.size,
                                 .memoryTypeIndex = index};
  if (vkAllocateMemory(h->device, &memory, NULL, &h->memory) != VK_SUCCESS ||
      vkBindBufferMemory(h->device, h->buffer, h->memory, 0) != VK_SUCCESS ||
      vkMapMemory(h->device, h->memory, 0, VK_WHOLE_SIZE, 0, &h->mapped) !=
          VK_SUCCESS)
    return 0;
  VkDescriptorBufferInfo info = {
      .buffer = h->buffer, .offset = 0, .range = bytes};
  VkWriteDescriptorSet write = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
                                .dstSet = h->set,
                                .dstBinding = 0,
                                .descriptorCount = 1,
                                .descriptorType =
                                    VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                                .pBufferInfo = &info};
  vkUpdateDescriptorSets(h->device, 1, &write, 0, NULL);
  h->capacity = bytes;
  return 1;
}
// 0 system/device error; 1 success; 2 device capacity/range; 3 invalid input.
EXPORT int32_t dyn_ui_vk_render(void *p, const uint32_t *input, uint32_t words,
                                uint8_t *rgba, uint32_t width,
                                uint32_t height) {
  Host *h = p;
  if (!h || !input || !rgba || words < 8 || !width || !height)
    return 3;
  uint64_t pixels = (uint64_t)width * height,
           total = ((uint64_t)words + pixels) * 4;
  if (total > h->properties.limits.maxStorageBufferRange || total > SIZE_MAX ||
      pixels + words > UINT32_MAX ||
      (width + 7ull) / 8 > h->properties.limits.maxComputeWorkGroupCount[0] ||
      (height + 7ull) / 8 > h->properties.limits.maxComputeWorkGroupCount[1])
    return 2;
  if (!storage(h, total))
    return 0;
  memcpy(h->mapped, input, (size_t)words * 4);
  memcpy((uint32_t *)h->mapped + words, rgba, (size_t)pixels * 4);
  uint32_t *data = h->mapped;
  data[0] = width;
  data[1] = height;
  data[4] = words;
  VkMappedMemoryRange range = {.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
                               .memory = h->memory,
                               .offset = 0,
                               .size = VK_WHOLE_SIZE};
  if (!h->coherent &&
      vkFlushMappedMemoryRanges(h->device, 1, &range) != VK_SUCCESS)
    return 0;
  if (vkResetCommandBuffer(h->command, 0) != VK_SUCCESS ||
      vkResetFences(h->device, 1, &h->fence) != VK_SUCCESS)
    return 0;
  VkCommandBufferBeginInfo begin = {
      .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
      .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
  if (vkBeginCommandBuffer(h->command, &begin) != VK_SUCCESS)
    return 0;
  VkMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
                             .srcAccessMask = VK_ACCESS_HOST_WRITE_BIT,
                             .dstAccessMask = VK_ACCESS_SHADER_READ_BIT |
                                              VK_ACCESS_SHADER_WRITE_BIT};
  vkCmdPipelineBarrier(h->command, VK_PIPELINE_STAGE_HOST_BIT,
                       VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &barrier, 0,
                       NULL, 0, NULL);
  vkCmdBindPipeline(h->command, VK_PIPELINE_BIND_POINT_COMPUTE, h->pipeline);
  vkCmdBindDescriptorSets(h->command, VK_PIPELINE_BIND_POINT_COMPUTE, h->layout,
                          0, 1, &h->set, 0, NULL);
  vkCmdDispatch(h->command, (width + 7) / 8, (height + 7) / 8, 1);
  barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
  barrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
  vkCmdPipelineBarrier(h->command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                       VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier, 0, NULL, 0,
                       NULL);
  if (vkEndCommandBuffer(h->command) != VK_SUCCESS)
    return 0;
  VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                         .commandBufferCount = 1,
                         .pCommandBuffers = &h->command};
  if (vkQueueSubmit(h->queue, 1, &submit, h->fence) != VK_SUCCESS ||
      vkWaitForFences(h->device, 1, &h->fence, VK_TRUE, UINT64_MAX) !=
          VK_SUCCESS)
    return 0;
  if (!h->coherent &&
      vkInvalidateMappedMemoryRanges(h->device, 1, &range) != VK_SUCCESS)
    return 0;
  memcpy(rgba, (uint32_t *)h->mapped + words, (size_t)pixels * 4);
  return 1;
}
