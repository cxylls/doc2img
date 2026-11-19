import os
import glob
from PIL import Image
import numpy as np

def remove_blank_lines(image, threshold=240):
    """
    去除图片首尾的空白行，保留内部空白行
    
    参数:
    image: PIL Image对象
    threshold: 空白判断阈值(0-255)，值越大越宽松
    
    返回:
    去除首尾空白行后的PIL Image对象
    """
    # 转换为灰度图
    gray = image.convert('L')
    pixels = np.array(gray)
    
    # 从顶部开始找第一个非空白行（只要存在非空白像素）
    top_cut = 0
    for i in range(pixels.shape[0]):
        # 检查该行是否有像素值小于阈值
        if np.any(pixels[i, :] < threshold):
            top_cut = i
            break
    
    # 从底部开始找第一个非空白行
    bottom_cut = 0
    for i in range(pixels.shape[0] - 1, -1, -1):
        # 检查该行是否有像素值小于阈值
        if np.any(pixels[i, :] < threshold):
            bottom_cut = pixels.shape[0] - i - 1
            break
    
    # 如果整张图都是空白，返回原图
    if top_cut == 0 and bottom_cut == 0:
        return image
    
    # 计算裁剪区域
    crop_box = (0, top_cut, image.width, image.height - bottom_cut)
    return image.crop(crop_box)

def stitch_images_vertical(images, spacing=0, align='center'):
    """
    垂直拼接多张图片，去除图片间的空白行
    
    参数:
    images: PIL Image对象列表
    spacing: 图片间距(像素)，即空行数
    align: 对齐方式 ('left', 'center', 'right')
    
    返回:
    拼接后的PIL Image对象
    """
    if not images:
        raise ValueError("图片列表为空")
    
    # 计算总尺寸
    widths = [img.width for img in images]
    heights = [img.height for img in images]
    
    max_width = max(widths)
    total_height = sum(heights) + spacing * (len(images) - 1)
    
    # 创建新画布(白色背景)
    result = Image.new('RGB', (max_width, total_height), (255, 255, 255))
    
    # 逐张粘贴图片
    y_offset = 0
    for i, img in enumerate(images):
        if align == 'left':
            x_offset = 0
        elif align == 'right':
            x_offset = max_width - img.width
        else:  # center
            x_offset = (max_width - img.width) // 2
        
        result.paste(img, (x_offset, y_offset))
        y_offset += img.height + spacing
    
    return result

def process_and_stitch_images(folder_path, blank_threshold=240,
                              output_path='output.png', spacing=0, align='center',
                              top_margin=0, bottom_margin=0):
    """
    主函数：处理文件夹中的图片并拼接，去除空白行

    参数:
    folder_path: 图片文件夹路径
    blank_threshold: 空白判断阈值(0-255)
    output_path: 输出文件路径
    spacing: 图片间距
    align: 对齐方式
    top_margin: 顶部留白行数
    bottom_margin: 底部留白行数
    """
    # 支持的图片格式
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
    
    # 获取所有图片文件
    image_paths = []
    for ext in extensions:
        image_paths.extend(glob.glob(os.path.join(folder_path, ext)))
    
    if not image_paths:
        print(f"在文件夹 {folder_path} 中未找到图片文件")
        return
    
    # 按文件名排序
    image_paths.sort()
    print(f"找到 {len(image_paths)} 张图片，按以下顺序处理:")
    for path in image_paths:
        print(f"  {os.path.basename(path)}")
    
    processed_images = []
    
    # 处理每张图片
    for i, img_path in enumerate(image_paths):
        try:
            # 打开图片
            img = Image.open(img_path)
            print(f"处理图片 {i+1}/{len(image_paths)}: {os.path.basename(img_path)} "
                  f"(原始尺寸: {img.size[0]}x{img.size[1]})")
            
            # 去除空白行
            cropped_img = remove_blank_lines(img, blank_threshold)
            print(f"  去除空白行后尺寸: {cropped_img.size[0]}x{cropped_img.size[1]}")
            
            processed_images.append(cropped_img)
            
        except Exception as e:
            print(f"处理图片 {img_path} 时出错: {e}")
            continue
    
    if not processed_images:
        print("没有成功处理的图片")
        return
    
    # 拼接图片
    print("开始拼接图片...")
    result_image = stitch_images_vertical(processed_images, spacing, align)
    
    # 添加首尾留白
    if top_margin > 0 or bottom_margin > 0:
        width, height = result_image.size
        new_height = height + top_margin + bottom_margin
        
        # 创建带留白的新图片
        new_image = Image.new('RGB', (width, new_height), (255, 255, 255))
        new_image.paste(result_image, (0, top_margin))
        result_image = new_image
    
    # 自动选择保存格式
    _, height = result_image.size
    if height <= 65500:
        # 高度在JPEG支持范围内，保存为JPEG
        if not output_path.lower().endswith(('.jpg', '.jpeg')):
            base_name = os.path.splitext(output_path)[0]
            output_path = base_name + '.jpg'
        format_name = "JPEG"
    else:
        # 高度超过JPEG限制，保存为PNG
        if not output_path.lower().endswith('.png'):
            base_name = os.path.splitext(output_path)[0]
            output_path = base_name + '.png'
        format_name = "PNG"
    
    # 保存结果
    result_image.save(output_path)
    print(f"拼接完成! 结果已保存至: {output_path}")
    print(f"最终图片尺寸: {result_image.size[0]}x{result_image.size[1]}")
    print(f"保存格式: {format_name}")
    if top_margin > 0 or bottom_margin > 0:
        print(f"顶部留白: {top_margin}行，底部留白: {bottom_margin}行")

if __name__ == "__main__":
    # 使用示例
    folder_path = input("请输入图片文件夹路径: ").strip().strip('"')
    
    # 获取用户输入的空白阈值
    try:
        blank_threshold = int(input("请输入空白判断阈值(0-255，默认240): ") or "240")
        if blank_threshold < 0 or blank_threshold > 255:
            print("阈值无效，使用默认值240")
            blank_threshold = 240
    except ValueError:
        print("输入无效，使用默认值240")
        blank_threshold = 240
    
    # 可选参数
    try:
        spacing = int(input("请输入图片间距(像素，默认0): ") or "0")
    except ValueError:
        spacing = 0
    
    align = input("请输入对齐方式(left/center/right，默认center): ") or "center"
    
    output_path = input("请输入输出文件路径(默认output.png): ") or "output.png"
    
    # 获取首尾留白参数
    try:
        top_margin = int(input("请输入顶部留白行数(默认0): ") or "0")
        bottom_margin = int(input("请输入底部留白行数(默认0): ") or "0")
    except ValueError:
        print("输入无效，使用默认值0")
        top_margin = 0
        bottom_margin = 0
    
    # 执行处理
    process_and_stitch_images(
        folder_path=folder_path,
        blank_threshold=blank_threshold,
        output_path=output_path,
        spacing=spacing,
        align=align,
        top_margin=top_margin,
        bottom_margin=bottom_margin
    )