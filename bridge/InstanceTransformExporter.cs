using CUE4Parse.UE4.Objects.Core.Math;

/// <summary>Native foliage transforms avoid hundreds of thousands of JSON records.</summary>
internal sealed class InstanceTransformExporter : IDisposable
{
    private readonly string _root, _name, _path, _pending;
    private BinaryWriter? _writer;
    private bool _complete;

    public InstanceTransformExporter(string outputDirectory)
    {
        _root = Path.GetFullPath(outputDirectory);
        _name = "instances-" + Guid.NewGuid().ToString("N") + ".bin";
        _path = Path.Combine(_root, _name);
        _pending = _path + ".partial";
    }

    public object Write(IReadOnlyList<FTransform> transforms)
    {
        if (_complete) throw new InvalidOperationException("The instance stream is complete.");
        if (_writer is null)
        {
            Directory.CreateDirectory(_root);
            _writer = new BinaryWriter(new FileStream(_pending, FileMode.CreateNew,
                FileAccess.Write, FileShare.None, 262144, FileOptions.SequentialScan));
        }
        var offset = _writer.BaseStream.Position;
        foreach (var transform in transforms)
        {
            _writer.Write(transform.Translation.X); _writer.Write(transform.Translation.Y); _writer.Write(transform.Translation.Z);
            _writer.Write(transform.Rotation.W); _writer.Write(transform.Rotation.X); _writer.Write(transform.Rotation.Y); _writer.Write(transform.Rotation.Z);
            _writer.Write(transform.Scale3D.X); _writer.Write(transform.Scale3D.Y); _writer.Write(transform.Scale3D.Z);
        }
        return new { binaryInstances = new { version = 1, file = _name, byteOffset = offset, dtype = "<f4", shape = new[] { transforms.Count, 10 } } };
    }

    public void Complete()
    {
        if (_complete) return;
        if (_writer is not null)
        {
            _writer.Dispose();
            _writer = null;
            File.Move(_pending, _path);
        }
        _complete = true;
    }

    public void Dispose()
    {
        _writer?.Dispose();
        if (!_complete && File.Exists(_pending)) File.Delete(_pending);
    }

    public static object Export(IReadOnlyList<FTransform> transforms, string outputDirectory)
    {
        using var batch = new InstanceTransformExporter(outputDirectory);
        var descriptor = batch.Write(transforms);
        batch.Complete();
        return descriptor;
    }
}
