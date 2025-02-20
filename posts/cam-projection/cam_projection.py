import numpy as np
import math

np.set_printoptions(precision=6, suppress=True)

PRINT_DEBUG = True

def projection_by_vertical_fov(fov_y_rad, aspect_ratio_width_divided_by_height, near, far, x_offset, y_offset):
    tan_half_fov = np.tan(fov_y_rad * 0.5)

    matrix = np.zeros((4, 4))
    matrix[0, 0] = 1 / (aspect_ratio_width_divided_by_height * tan_half_fov)
    matrix[1, 1] = 1 / tan_half_fov
    matrix[2, 2] = -(far + near) / (far - near)
    matrix[2, 3] = -(2.0 * far * near) / (far - near)
    matrix[3, 2] = -1.0
    matrix[3, 3] = 0

    matrix[0, 2] = x_offset
    matrix[1, 2] = y_offset

    return matrix

def project_to_img_coords_via_perspective_projection_matrix(point_3d: np.ndarray, fov_vertical_deg: int, image_width: int, image_height: int, near: float = 0.0001, far: float = 1000000, x_offset: float = 0.0, y_offset: float = 0.0) -> np.ndarray:
    projection_matrix = projection_by_vertical_fov(math.radians(fov_vertical_deg), image_width / image_height, near, far, x_offset, y_offset)
    print(f"{projection_matrix=}")
    point_4 = np.array([point_3d[0], point_3d[1], point_3d[2], 1.])
    print(f"{point_4=}")
    
    unity_flip = False
    if unity_flip:
        # https://docs.unity3d.com/2020.1/Documentation/ScriptReference/Matrix4x4.Perspective.html
        # ```
        # The returned matrix embeds a z-flip operation whose purpose is to cancel the z-flip performed by the camera view matrix. 
        # If the view matrix is an identity or some custom matrix that doesn't perform a z-flip, consider multiplying the third column of the projection matrix (i.e. m02, m12, m22 and m32) by -1.
        # ```

        flip_third_col = True
        if flip_third_col:
            projection_matrix[:,2] = -projection_matrix[:,2]
        
        # alternatively
        flip_z = not flip_third_col
        if flip_z:
            point_4[2] = -point_4[2]

    # perspective projection
    proj_x, proj_y, proj_z, proj_w = np.dot(projection_matrix, point_4)
    print("projection pre-division", proj_x, proj_y, proj_z, proj_w)
    
    # perspective division
    proj_x, proj_y, proj_z = proj_x / proj_w, proj_y / proj_w, proj_z / proj_w
    print("projection post-division", proj_x, proj_y, proj_z)
    
    # full-viewport transform
    img_x = proj_x * (image_width / 2) + image_width / 2
    img_y = proj_y * (image_height / 2) + image_height / 2
     
    return int(img_x), int(img_y)

if __name__ == "__main__":
    img_x, img_y = project_to_img_coords_via_perspective_projection_matrix(np.array([-0.78123814, 0.6558889, -3.1099024]), 45.0, 1280, 720, 0.1, 100)
    print(img_x, img_y)